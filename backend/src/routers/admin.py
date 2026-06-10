"""管理端路由 — 用户管理 + 知识库 + 文档管理 (admin only)"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import hash_password, require_admin
from src.config import MINIO_RAW_BUCKET
from src.db import get_db
from src.minio_client import upload_raw_pdf
from src.models import (
    DocumentTask,
    KnowledgeBase,
    TaskStatus,
    User,
)
from src.schemas import (
    DocumentResponse,
    KBCreateRequest,
    KBResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from src.ws_manager import broadcast_doc_update, ws_manager

import fitz  # PyMuPDF


def _pdf_pages(data: bytes) -> int:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = doc.page_count
    doc.close()
    return pages


async def _submit_one_file(fi: dict, db: AsyncSession):
    """轻量单文件提交，不依赖 KeyManager"""
    from src.key_manager import TokenExhausted, get_key_manager

    key_mgr = get_key_manager()
    try:
        token = key_mgr.acquire(fi["pages"])
        key_mgr.release(token, fi["pages"])
    except TokenExhausted as e:
        stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
        r = await db.execute(stmt)
        t = r.scalar_one_or_none()
        if t:
            t.status = TaskStatus.FAILED
            t.error_msg = f"额度用完: {e}"
        await db.commit()
        return

    from src import mineru_client

    batch_id, md5_list = await mineru_client.submit_batch([fi], token=token)
    stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
    r = await db.execute(stmt)
    t = r.scalar_one_or_none()
    if t:
        t.batch_id = batch_id
        t.status = TaskStatus.PROCESSING
    await db.commit()

    from src.redis_client import enqueue_batch
    await enqueue_batch(batch_id, md5_list, token=token)


async def _cleanup_es_milvus(md5: str, pipeline_steps: dict | None) -> None:
    """删除 ES 和 Milvus 中属于该文档的全部 chunk。"""
    steps = pipeline_steps or {}

    # ES 清理
    es_step = steps.get("es_write", {})
    if es_step.get("status") == "done":
        es_index = es_step.get("target_index")
        if es_index:
            try:
                from src.search import _get_es
                es = _get_es()
                es.delete_by_query(
                    index=es_index,
                    body={"query": {"term": {"doc_id": md5}}},
                    refresh=True,
                )
            except Exception:
                pass

    # Milvus 清理
    mv_step = steps.get("milvus", {})
    if mv_step.get("status") == "done":
        mv_collection = mv_step.get("target_collection")
        if mv_collection:
            try:
                from pymilvus import Collection
                from src.search import _connect_milvus
                _connect_milvus()
                col = Collection(mv_collection)
                col.delete(f'doc_id == "{md5}"')
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
    if kb.slug == "zhong_guo_quan_ke":
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
    if kb.slug == "zhong_guo_quan_ke":
        raise HTTPException(403, "默认知识库不支持上传文档，请新建知识库")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")

    file_md5 = hashlib.md5(content).hexdigest()

    # Check for existing document
    existing_result = await db.execute(
        select(DocumentTask).where(DocumentTask.md5 == file_md5)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.kb_id = kb_id
        await db.commit()
        await broadcast_doc_update(existing)
        return DocumentResponse.model_validate(existing)

    raw_path = upload_raw_pdf(file_md5, file.filename or "unknown", content)
    from src.models import default_pipeline_steps
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "done", "ts": datetime.now(timezone.utc).isoformat()}
    task = DocumentTask(
        kb_id=kb_id,
        md5=file_md5,
        original_name=file.filename or "unknown",
        raw_minio_path=f"{MINIO_RAW_BUCKET}/{raw_path}",
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
        task.status = TaskStatus.FAILED
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

    md5 = task.md5
    steps = task.pipeline_steps
    kb_id = task.kb_id

    await _cleanup_es_milvus(md5, steps)
    await db.delete(task)
    await db.commit()

    if kb_id:
        await ws_manager.broadcast(str(kb_id), {
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
    from src.models import PIPELINE_STEPS_ORDER

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

    now = datetime.now(timezone.utc).isoformat()

    # 重置当前及后续步骤
    for step in PIPELINE_STEPS_ORDER[PIPELINE_STEPS_ORDER.index(retry_from):]:
        steps[step] = {"status": "pending", "ts": now}
    task.pipeline_steps = steps

    if retry_from == "mineru":
        task.status = TaskStatus.PENDING
        task.error_msg = None
        await db.commit()
        await broadcast_doc_update(task)

        if task.batch_id:
            from src.key_manager import get_key_manager
            from src.redis_client import enqueue_batch

            key_mgr = get_key_manager()
            try:
                token = next(iter(key_mgr._tokens)) if key_mgr._tokens else ""
            except Exception:
                token = ""
            await enqueue_batch(task.batch_id, [task.md5], token=token)
    else:
        # chunking/embedding/es_write/milvus → 回到 PARSED，Worker 自动重跑
        task.status = TaskStatus.PARSED
        task.error_msg = None
        await db.commit()
        await broadcast_doc_update(task)

    return {"ok": True, "retry_from": retry_from}
