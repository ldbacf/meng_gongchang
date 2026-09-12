"""管理端路由 — 用户管理 + 知识库 + 文档管理 (admin only)"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge_base import KBKind, resolve_kb_kind
from app.infrastructure.settings import get_settings
from app.interface.security import hash_password, require_admin
from app.infrastructure.db.session import get_db
from app.infrastructure.db.models import (
    DocumentTask,
    KnowledgeBase,
    TaskStatus,
    User,
)
from app.interface.schemas import (
    DocumentResponse,
    KBCreateRequest,
    KBResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.infrastructure.ws_manager import broadcast_doc_update

import fitz  # PyMuPDF


def _pdf_pages(data: bytes) -> int:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = doc.page_count
    doc.close()
    return pages


async def _submit_one_file(fi: dict, db: AsyncSession):
    """轻量单文件提交 — 统一经 SubmissionService（O-3.5，三阶段额度）。"""
    from app.interface.deps import get_container

    svc = get_container().get_submission_service()
    results = await svc.submit([fi])
    if results and not results[0]["ok"]:
        # 保持原行为：失败向上抛（调用方 except 处理 + 响应置 FAILED）
        raise Exception(results[0]["error"])


async def _cleanup_es_milvus(md5: str, pipeline_steps: dict | None, task_batch_id: str | None = None) -> None:
    """删除 ES 和 Milvus 中属于该文档的全部 chunk。

    doc_id 硬切点（契约口径 md5[:8]），删除按**双口径**兼容：
    - `task_batch_id`：预置文献的 ES doc_id（article_id）；
    - `md5[:8]`：统一后的契约 doc_id；
    - `md5`：存量旧口径（在线通用 KB 曾用全 32 位 md5 作 doc_id）。
    三者取并集删除，新旧 chunk 均能清理。
    """
    candidate_doc_ids = list(dict.fromkeys(filter(None, [task_batch_id, md5[:8], md5])))
    steps = pipeline_steps or {}

    # ES 清理
    es_step = steps.get("es_write", {})
    if es_step.get("status") == "done":
        es_index = es_step.get("target_index")
        if es_index and candidate_doc_ids:
            try:
                from app.infrastructure.search import get_es_client
                es = get_es_client()
                es.delete_by_query(
                    index=es_index,
                    body={"query": {"terms": {"doc_id": candidate_doc_ids}}},
                    refresh=True,
                )
            except Exception:
                pass

    # Milvus 清理
    mv_step = steps.get("milvus", {})
    if mv_step.get("status") == "done":
        mv_collection = mv_step.get("target_collection")
        if mv_collection and candidate_doc_ids:
            try:
                from pymilvus import Collection
                from app.infrastructure.search import connect_milvus
                connect_milvus()
                col = Collection(mv_collection)
                quoted = ", ".join(f'"{d}"' for d in candidate_doc_ids)
                col.delete(f"doc_id in [{quoted}]")
            except Exception:
                pass


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── 用户管理 ────────────────────────────────────────────────


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [UserResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    req: UserCreateRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    req: UserUpdateRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")

    if req.enabled is not None and _admin.id == user.id:
        raise HTTPException(400, "不能禁用自己")

    if req.enabled is not None:
        user.enabled = req.enabled
    if req.role is not None:
        user.role = req.role

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")
    if _admin.id == user.id:
        raise HTTPException(400, "不能删除自己")
    await db.delete(user)
    await db.commit()
    return {"ok": True}


# ── 知识库管理 ──────────────────────────────────────────────


@router.get("/knowledge-bases", response_model=list[KBResponse])
async def list_knowledge_bases(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeBase).order_by(KnowledgeBase.created_at.asc())
    )
    kbs = result.scalars().all()
    out = []
    for kb in kbs:
        count_result = await db.execute(
            select(func.count(DocumentTask.id)).where(DocumentTask.kb_id == kb.id)
        )
        doc_count = count_result.scalar() or 0
        ready_result = await db.execute(
            select(func.count(DocumentTask.id)).where(
                DocumentTask.kb_id == kb.id,
                DocumentTask.status == TaskStatus.PARSED,
            )
        )
        ready_count = ready_result.scalar() or 0
        out.append(KBResponse(
            id=kb.id, name=kb.name, description=kb.description,
            slug=kb.slug, es_index=kb.es_index,
            milvus_collection=kb.milvus_collection,
            created_at=kb.created_at,
            document_count=doc_count,
            has_ready_docs=ready_count > 0,
        ))
    return out


@router.post("/knowledge-bases", response_model=KBResponse)
async def create_knowledge_base(
    req: KBCreateRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.slug == req.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"标识 '{req.slug}' 已存在")

    es_index = f"kb_{req.slug}"
    milvus_collection = f"kb_{req.slug}"

    existing_es = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.es_index == es_index)
    )
    if existing_es.scalar_one_or_none():
        raise HTTPException(400, f"ES 索引 '{es_index}' 已被占用，请换一个标识")

    kb = KnowledgeBase(
        name=req.name,
        description=req.description,
        slug=req.slug,
        # 新建 KB 一律 GENERIC（代码显式，不依赖列 server_default，防静默变 medical_default）
        kb_kind=KBKind.GENERIC.value,
        es_index=es_index,
        milvus_collection=milvus_collection,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KBResponse(
        id=kb.id, name=kb.name, description=kb.description,
        slug=kb.slug, es_index=kb.es_index,
        milvus_collection=kb.milvus_collection,
        created_at=kb.created_at,
        document_count=0, has_ready_docs=False,
    )


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if resolve_kb_kind(kb) is KBKind.MEDICAL_DEFAULT:
        raise HTTPException(403, "默认知识库不可删除")

    # Unlink docs (set kb_id=NULL instead of cascade delete for safety)
    doc_result = await db.execute(
        select(DocumentTask).where(DocumentTask.kb_id == kb_id)
    )
    for doc in doc_result.scalars().all():
        doc.kb_id = None
    await db.commit()

    await db.delete(kb)
    await db.commit()
    return {"ok": True}


# ── 文档管理 (KB-scoped) ────────────────────────────────────


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DocumentTask)
        .where(DocumentTask.kb_id == kb_id)
        .order_by(DocumentTask.created_at.desc())
        .limit(200)
    )
    return [DocumentResponse.model_validate(t) for t in result.scalars().all()]


@router.post("/knowledge-bases/{kb_id}/documents", response_model=DocumentResponse)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if resolve_kb_kind(kb) is KBKind.MEDICAL_DEFAULT:
        raise HTTPException(403, "默认知识库不支持上传文档，请新建知识库")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")

    file_md5 = hashlib.md5(content).hexdigest()

    from app.interface.deps import get_container

    minio = get_container().get_minio()

    # Check for existing document（O-3.7：KB 内查重；跨 KB 复制；禁止 reassign kb_id）
    existing_result = await db.execute(
        select(DocumentTask).where(DocumentTask.md5 == file_md5)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        if existing.kb_id != kb_id:
            from app.main import _copy_across_kb

            resp, _fi = await _copy_across_kb(
                existing, file_md5, file.filename or "unknown", content, kb_id, db,
            )
            return DocumentResponse(
                id=resp.id, original_name=resp.original_name, md5=resp.md5,
                status=resp.status, kb_id=kb_id,
            )
        if existing.status == TaskStatus.PARSED and minio.check_parsed_exists(file_md5):
            await db.commit()
            await broadcast_doc_update(existing)
            return DocumentResponse.model_validate(existing)
        # 同 KB 已存在：提示已存在（不 reassign、不自动重提交）
        return DocumentResponse.model_validate(existing)

    raw_path = minio.upload_raw_pdf(
        file_md5, file.filename or "unknown", content
    )
    from app.infrastructure.db.models import default_pipeline_steps
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "done", "ts": datetime.now(timezone.utc).isoformat()}
    task = DocumentTask(
        kb_id=kb_id,
        md5=file_md5,
        original_name=file.filename or "unknown",
        raw_minio_path=f"{get_settings().minio_raw_bucket}/{raw_path}",
        status=TaskStatus.PENDING,
        pipeline_steps=steps,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await broadcast_doc_update(task)

    # Submit to MinerU
    try:
        pages = _pdf_pages(content)
        await _submit_one_file(
            {"name": file.filename or "unknown", "data": content, "md5": file_md5, "pages": pages},
            db,
        )
        await db.refresh(task)
        await broadcast_doc_update(task)
    except Exception as e:
        task.set_status(TaskStatus.FAILED)
        task.error_msg = str(e)
        await db.commit()
        await db.refresh(task)
        await broadcast_doc_update(task)

    return DocumentResponse.model_validate(task)


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DocumentTask).where(DocumentTask.id == doc_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "文档不存在")

    kb_id = task.kb_id

    # DeleteDocumentService 按统一 doc_id 清理 ES/Milvus + 残留对账（O-3.6）
    from app.application.services.document_deletion import DocumentBusyError
    from app.interface.deps import get_container

    try:
        await get_container().get_delete_service().delete(task)
    except DocumentBusyError as e:
        raise HTTPException(409, str(e))

    await db.delete(task)
    await db.commit()

    if kb_id:
        from app.infrastructure.ws_manager import get_ws_registry
        await get_ws_registry().broadcast(str(kb_id), {
            "type": "doc_deleted", "doc_id": str(doc_id),
        })

    return {"ok": True}


@router.post("/documents/{doc_id}/retry")
async def retry_document(
    doc_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """从第一个失败的步骤重试"""
    from app.infrastructure.db.models import PIPELINE_STEPS_ORDER

    result = await db.execute(select(DocumentTask).where(DocumentTask.id == doc_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "文档不存在")

    steps = task.pipeline_steps
    if not steps:
        raise HTTPException(400, "无 pipeline 记录，请重新上传")

    # 找第一个非 done 的步骤
    retry_from = None
    for step in PIPELINE_STEPS_ORDER:
        s = steps.get(step, {"status": "pending"})
        if s["status"] != "done":
            retry_from = step
            break

    if retry_from is None:
        raise HTTPException(400, "所有步骤已完成，无需重试")

    now = datetime.now(timezone.utc).timestamp()  # ts 统一 float

    # 重置当前及后续步骤，dict() 强制新对象触发 SQLAlchemy JSONB 脏跟踪
    for step in PIPELINE_STEPS_ORDER[PIPELINE_STEPS_ORDER.index(retry_from):]:
        steps[step] = {"status": "pending", "ts": now}
    task.pipeline_steps = dict(steps)
    await db.commit()

    # RetryService 从 checkpoint 恢复（O-3.4）——
    # 索引失败 → reset + resume 队列消息（worker 续跑，禁重放已消费 batch）；
    # MinerU 失败 → 重新提交（新 batch_id）+ 旧批 superseded。
    from app.interface.deps import get_container

    result = await get_container().get_retry_service().retry(task)
    await broadcast_doc_update(task)

    return {"ok": True, "retry_from": retry_from, "kind": result["kind"]}
