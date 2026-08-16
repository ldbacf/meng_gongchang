"""FastAPI 网关 — 多 Key 额度管理 + 自动轮换"""

import hashlib
import traceback
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import fitz  # PyMuPDF
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.interface.deps import get_container
from src.config import CHUNK_SIZE, CORS_ORIGINS, MINIO_RAW_BUCKET, MINERU_BATCH_SIZE
from src.db import async_session, engine
from src.key_manager import TokenExhausted, get_key_manager
from src.mineru_client import submit_batch
from src.minio_client import check_parsed_exists, get_minio, init_buckets, upload_raw_pdf
from src.models import DocumentTask, TaskStatus
from src.redis_client import enqueue_batch
from src.schemas import TaskCreateResponse, TaskStatusResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # schema 演进由 Alembic 管理（backend/alembic/）：新建库 `alembic upgrade head`，
    # 已有库先 `alembic stamp 0002_checkpoint` 标记基线。此处仅做 DI 装配与启动。
    container = get_container()
    await container.start()  # DB 连通性校验 + MinIO 建桶 + bge-m3 预热（幂等）

    # 创建默认管理员
    from sqlalchemy import func as sql_func  # noqa: F811

    async with async_session() as session:
        from src.models import KnowledgeBase, User
        from src.auth import hash_password

        result = await session.execute(
            select(sql_func.count()).select_from(User)
        )
        count = result.scalar()
        if count == 0:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                role="admin",
                enabled=True,
            )
            session.add(admin)
            await session.commit()
            print("[API] 已创建默认管理员: admin / admin123")
            print("[API] 请在首次登录后修改密码!")

    # 创建默认知识库 + 回填现有文档
    async with async_session() as session:
        from src.models import KnowledgeBase, DocumentTask

        kb_result = await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.slug == "zhong_guo_quan_ke")
        )
        kb = kb_result.scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(
                name="中国全科医学",
                description="《中国全科医学》期刊文献库，收录1248篇论文，覆盖高血压、糖尿病、心血管、慢性病管理等全科医学领域",
                slug="zhong_guo_quan_ke",  # seed 标识（slug 仅此处使用，业务分支看 kb_kind）
                kb_kind="medical_default",
                es_index="chunks",
                milvus_collection="chunks",
            )
            session.add(kb)
            await session.commit()
            await session.refresh(kb)
            print(f"[API] 已创建默认知识库: {kb.name}")

        # 回填现有文档
        result = await session.execute(
            select(DocumentTask).where(DocumentTask.kb_id.is_(None))
        )
        orphan_docs = result.scalars().all()
        if orphan_docs:
            for doc in orphan_docs:
                doc.kb_id = kb.id
            await session.commit()
            print(f"[API] 已回填 {len(orphan_docs)} 份文档到默认知识库")

    # 预热 KeyManager（额度账本在 Redis）
    print("[API] KeyManager 启动:")
    print(await get_key_manager().usage_report())

    # 阶段 3：worker 已剥离为独立进程（app.application.worker / pipeline-worker），
    # API 进程不再内嵌消费队列——入库管线由独立 worker 驱动 IngestionGraph。
    yield

    await container.close()  # 统一 dispose（engine/redis/milvus/bge-m3/checkpointer）


app = FastAPI(
    title="MedRAG API",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _pdf_pages(data: bytes) -> int:
    """读取 PDF 页数"""
    doc = fitz.open(stream=data, filetype="pdf")
    pages = doc.page_count
    doc.close()
    return pages


# ── 多 Key 提交逻辑 ──────────────────────────────────────────

async def _submit_batches(
    to_submit: list[dict],
    session,
):
    """
    提交批次到 MinerU — 统一经 SubmissionService（O-3.5，收敛双入口）。

    to_submit: [{"name": "...", "data": b"...", "md5": "..."}]
    """
    from app.interface.deps import get_container

    svc = get_container().get_submission_service()
    for fi in to_submit:
        if "pages" not in fi:
            fi["pages"] = _pdf_pages(fi["data"])
    results = await svc.submit(to_submit)
    for r in results:
        if r["ok"]:
            print(f"  [API] {r['md5'][:8]}: 已提交 batch={r['batch_id']}")
        else:
            print(f"  [API] {r['md5'][:8]}: 提交失败: {r['error']}")


# ── 查重逻辑 ──────────────────────────────────────────────────

async def _handle_one_file(file, session, kb_id=None) -> tuple[TaskCreateResponse, dict | None]:
    filename = file.filename or "unknown"
    content = await file.read()
    if not content:
        raise HTTPException(400, f"{filename} 为空")
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(400, f"{filename} 超过 200MB")

    file_md5 = _md5(content)

    stmt = select(DocumentTask).where(DocumentTask.md5 == file_md5)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # O-3.7：禁止 reassign kb_id（归属漂移）——跨 KB 重传复制新 task（保留 parsed 引用）
        if kb_id and existing.kb_id != kb_id:
            return await _copy_across_kb(
                existing, file_md5, filename, content, kb_id, session
            )
        if existing.status == TaskStatus.PARSED and check_parsed_exists(file_md5):
            await session.commit()
            return TaskCreateResponse(
                id=existing.id, md5=existing.md5,
                original_name=existing.original_name,
                status=existing.status,
                raw_minio_path=existing.raw_minio_path,
                message="秒传: 解析产物已存在",
            ), None

        existing.reset(reason="reupload")  # 人为重开（重传/重扫），非状态机迁移
        existing.error_msg = None
        await session.commit()
        return TaskCreateResponse(
            id=existing.id, md5=existing.md5,
            original_name=existing.original_name,
            status=TaskStatus.PENDING,
            raw_minio_path=existing.raw_minio_path,
            message="重试: 重新提交解析",
        ), {"name": filename, "data": content, "md5": file_md5}


async def _copy_across_kb(
    existing, file_md5: str, filename: str, content: bytes, kb_id, session,
) -> tuple[TaskCreateResponse, dict | None]:
    """跨 KB 重传（O-3.7）：复制新 task 到目标 KB，保留 parsed 引用，不 reassign 原 task。

    - 已解析（parsed_minio_path 存在）：新 task 置 PARSED + 发 resume 队列消息
      （batch_id=新 task.id，worker 从 checkpoint 续跑直接重索引到新 KB）。
    - 未解析：新 task 置 PENDING，返回 fi 由调用方重新提交解析。
    """
    from datetime import datetime as _dt, timezone as _tz

    from src.models import default_pipeline_steps

    steps = default_pipeline_steps()
    now = _dt.now(_tz.utc).timestamp()
    steps["upload"] = {"status": "done", "ts": now}
    parsed = bool(existing.parsed_minio_path)
    if parsed:
        steps["mineru"] = {"status": "done", "ts": now}

    task = DocumentTask(
        kb_id=kb_id,
        md5=file_md5,
        original_name=existing.original_name,
        raw_minio_path=existing.raw_minio_path,
        parsed_minio_path=existing.parsed_minio_path,
        status=TaskStatus.PARSED if parsed else TaskStatus.PENDING,
        pipeline_steps=steps,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if parsed:
        # 复用解析产物：resume 消息触发 worker 重索引（不经 MinerU）
        from app.interface.deps import get_container

        await get_container().get_queue().enqueue(
            str(task.id), [file_md5], token_id="", mode="resume"
        )
        return TaskCreateResponse(
            id=task.id, md5=task.md5, original_name=task.original_name,
            status=task.status, raw_minio_path=task.raw_minio_path,
            message="跨知识库复制: 复用解析产物，待索引",
        ), None

    return TaskCreateResponse(
        id=task.id, md5=task.md5, original_name=task.original_name,
        status=task.status, raw_minio_path=task.raw_minio_path,
        message="跨知识库复制: 待提交解析",
    ), {"name": filename, "data": content, "md5": file_md5}

    # 新文件
    from datetime import datetime as _dt, timezone as _tz
    from src.models import default_pipeline_steps

    raw_path = upload_raw_pdf(file_md5, filename, content)
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "done", "ts": _dt.now(_tz.utc).timestamp()}  # ts 统一 float
    task = DocumentTask(
        kb_id=kb_id,
        md5=file_md5, original_name=filename,
        raw_minio_path=f"{MINIO_RAW_BUCKET}/{raw_path}",
        status=TaskStatus.PENDING,
        pipeline_steps=steps,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    return TaskCreateResponse(
        id=task.id, md5=task.md5,
        original_name=task.original_name,
        status=task.status,
        raw_minio_path=task.raw_minio_path,
        message="新文件: 待提交解析",
    ), {"name": filename, "data": content, "md5": file_md5}


# ── 注册路由 ──────────────────────────────────────────────

from src.auth import get_current_user, require_admin  # noqa: E402
from src.routers.auth import router as auth_router  # noqa: E402
from src.routers.chat import router as chat_router  # noqa: E402
from src.routers.admin import router as admin_router  # noqa: E402
from src.routers.ws import router as ws_router  # noqa: E402

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(ws_router)


# ── API 端点 ──────────────────────────────────────────────────

@app.post("/api/v1/documents", response_model=TaskCreateResponse)
async def upload_document(
    file: UploadFile = File(...),
    _user=Depends(get_current_user),
):
    async with async_session() as session:
        resp, fi = await _handle_one_file(file, session)
        if fi is None:
            return resp  # 秒传

        try:
            await _submit_batches([fi], session)
            resp.status = TaskStatus.PROCESSING
            resp.message = "已提交解析任务"
        except Exception as e:
            traceback.print_exc()
            resp.status = TaskStatus.FAILED
            resp.message = f"提交失败: {e}"
            stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
            r = await session.execute(stmt)
            t = r.scalar_one_or_none()
            if t:
                t.set_status(TaskStatus.FAILED)
                t.error_msg = str(e)
                await session.commit()

        return resp


@app.post("/api/v1/documents/batch", response_model=list[TaskCreateResponse])
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    kb_id: str | None = Query(None),
    _user=Depends(get_current_user),
):
    if len(files) > CHUNK_SIZE:
        raise HTTPException(400, f"单次最多 {CHUNK_SIZE} 个文件")

    import uuid as _uuid
    _kb_id = _uuid.UUID(kb_id) if kb_id else None

    responses = []
    to_submit = []

    async with async_session() as session:
        for file in files:
            resp, fi = await _handle_one_file(file, session, kb_id=_kb_id)
            responses.append(resp)
            if fi is not None:
                to_submit.append(fi)

    if to_submit:
        try:
            async with async_session() as session:
                await _submit_batches(to_submit, session)

            for resp in responses:
                if resp.status == TaskStatus.PENDING:
                    resp.status = TaskStatus.PROCESSING
                    resp.message = "已提交解析任务"
        except Exception as e:
            traceback.print_exc()
            async with async_session() as session:
                for fi in to_submit:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
                    r = await session.execute(stmt)
                    t = r.scalar_one_or_none()
                    if t:
                        t.set_status(TaskStatus.FAILED)
                        t.error_msg = str(e)
                await session.commit()
            for resp in responses:
                if resp.status == TaskStatus.PENDING:
                    resp.status = TaskStatus.FAILED
                    resp.message = f"提交失败: {e}"

    return responses


@app.get("/api/v1/documents/{doc_id}", response_model=TaskStatusResponse)
async def get_document_status(
    doc_id: uuid.UUID,
    _user=Depends(get_current_user),
):
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.id == doc_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


@app.get("/api/v1/documents/md5/{md5}", response_model=TaskStatusResponse)
async def get_document_by_md5(
    md5: str,
    _user=Depends(get_current_user),
):
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


@app.get("/api/v1/documents/{doc_id}/pdf")
async def get_document_pdf(
    doc_id: str,
    user=Depends(get_current_user),
):
    """返回 PDF 预签名 URL — 支持 DocumentTask 查找 + MinIO 直接查找"""
    from datetime import timedelta

    from src.config import MINIO_RAW_BUCKET, MINIO_CHUNKS_BUCKET
    from src.minio_client import get_minio

    # 方案 A: 通过 DocumentTask 查找
    presigned = await _try_document_task_pdf(doc_id)
    if presigned:
        return {"pdf_url": presigned, "total_pages": 0}

    # 方案 B: 直接去 MinIO 的 raw-docs 桶按 doc_id 扫描
    presigned = _try_minio_direct(doc_id)
    if presigned:
        return {"pdf_url": presigned, "total_pages": 0}

    raise HTTPException(404, f"文档不存在: {doc_id}")


@app.get("/api/v1/documents/{doc_id}/pdf/stream")
async def stream_document_pdf(
    doc_id: str,
    user=Depends(get_current_user),
):
    """代理 PDF 内容流 — 后端从 MinIO 读取 PDF 直接流式返回，不再暴露 presigned URL 给前端"""
    from fastapi.responses import StreamingResponse

    from src.config import MINIO_RAW_BUCKET
    from src.minio_client import get_minio

    client = get_minio()
    object_path = await _find_pdf_object_name(doc_id)
    if not object_path:
        raise HTTPException(404, f"文档不存在: {doc_id}")

    try:
        response = client.get_object(MINIO_RAW_BUCKET, object_path)
    except Exception as e:
        raise HTTPException(502, f"读取 PDF 失败: {e}")

    return StreamingResponse(
        response.stream(amt=65536),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc_id}.pdf"',
            "Cache-Control": "public, max-age=3600",
            "Accept-Ranges": "bytes",
        },
    )


async def _find_pdf_object_name(doc_id: str) -> str | None:
    """查找 PDF 在 MinIO raw-docs 桶中的对象路径

    按优先级:
    1. DocumentTask 表（通过 id / md5 / batch_id）
    2. 直接扫 MinIO raw-docs 前缀
    3. ES 反查 md5 再扫 MinIO
    """
    from datetime import timedelta

    from src.config import ES_INDEX, MINIO_RAW_BUCKET
    from src.minio_client import get_minio
    from src.models import DocumentTask

    from src.db import async_session

    # ── 1. 先查 DocumentTask 表 ──
    async with async_session() as session:
        task = None
        try:
            uid = uuid.UUID(doc_id)
        except ValueError:
            uid = None
        else:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.id == uid)
            )
            task = result.scalar_one_or_none()

        if not task:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.md5 == doc_id)
            )
            task = result.scalar_one_or_none()

        if not task:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.batch_id == doc_id).limit(1)
            )
            task = result.scalar_one_or_none()

        if task and task.raw_minio_path:
            if task.raw_minio_path.startswith(f"{MINIO_RAW_BUCKET}/"):
                return task.raw_minio_path[len(f"{MINIO_RAW_BUCKET}/"):]
            return task.raw_minio_path

    # ── 2. 直接按 doc_id 前缀扫 MinIO ──
    client = get_minio()

    for prefix in (f"{doc_id}/", doc_id):
        objects = client.list_objects(MINIO_RAW_BUCKET, prefix=prefix, recursive=True)
        for obj in objects:
            if obj.object_name.endswith(".pdf"):
                return obj.object_name

    # ── 3. 查 ES L0 chunk 反拿 md5 → 再去 MinIO 扫 ──
    try:
        from src.search import get_es_client

        es = get_es_client()
        resp = es.search(
            index=ES_INDEX,
            body={
                "size": 1,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"doc_id": doc_id}},
                            {"term": {"level": "L0"}},
                        ]
                    }
                },
                "_source": ["md5"],
            },
        )
        hits = resp.get("hits", {}).get("hits", [])
        if hits:
            md5 = hits[0]["_source"].get("md5")
            if md5:
                objects = client.list_objects(
                    MINIO_RAW_BUCKET, prefix=f"{md5}/", recursive=True
                )
                for obj in objects:
                    if obj.object_name.endswith(".pdf"):
                        return obj.object_name
    except Exception:
        pass

    return None


async def _try_document_task_pdf(doc_id: str) -> str | None:
    """通过 DocumentTask 表查找 PDF"""
    from datetime import timedelta

    from src.config import MINIO_RAW_BUCKET
    from src.minio_client import get_minio
    from src.models import DocumentTask

    from src.db import async_session

    async with async_session() as session:
        task = None
        try:
            uid = uuid.UUID(doc_id)
        except ValueError:
            uid = None
        else:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.id == uid)
            )
            task = result.scalar_one_or_none()

        if not task:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.md5 == doc_id)
            )
            task = result.scalar_one_or_none()

        if not task:
            result = await session.execute(
                select(DocumentTask).where(DocumentTask.md5.startswith(doc_id)).limit(
                    1
                )
            )
            task = result.scalar_one_or_none()

        if not task:
            return None

        client = get_minio()
        if task.raw_minio_path.startswith(f"{MINIO_RAW_BUCKET}/"):
            object_path = task.raw_minio_path[len(f"{MINIO_RAW_BUCKET}/"):]
        else:
            object_path = task.raw_minio_path

        return client.presigned_get_object(
            MINIO_RAW_BUCKET,
            object_path,
            expires=timedelta(hours=1),
        )


def _try_minio_direct(doc_id: str) -> str | None:
    """直接从 MinIO 查找 PDF — 先试 doc_id 前缀，再试 ES L0 反查 md5"""
    from datetime import timedelta

    from src.config import ES_INDEX, MINIO_RAW_BUCKET
    from src.minio_client import get_minio

    client = get_minio()

    # 步骤 A: 直接按 doc_id 前缀扫描
    objects = client.list_objects(
        MINIO_RAW_BUCKET, prefix=f"{doc_id}/", recursive=True
    )
    for obj in objects:
        if not obj.object_name.endswith(".pdf"):
            continue
        return client.presigned_get_object(
            MINIO_RAW_BUCKET, obj.object_name, expires=timedelta(hours=1)
        )

    objects = client.list_objects(
        MINIO_RAW_BUCKET, prefix=f"{doc_id}", recursive=True
    )
    for obj in objects:
        if not obj.object_name.endswith(".pdf"):
            continue
        return client.presigned_get_object(
            MINIO_RAW_BUCKET, obj.object_name, expires=timedelta(hours=1)
        )

    # 步骤 B: 查 ES L0 chunk 反拿 md5 → 再去 MinIO 按 md5 扫
    try:
        from src.search import get_es_client

        es = get_es_client()

        resp = es.search(
            index=ES_INDEX,
            body={
                "size": 1,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"doc_id": doc_id}},
                            {"term": {"level": "L0"}},
                        ]
                    }
                },
                "_source": ["md5"],
            },
        )
        hits = resp.get("hits", {}).get("hits", [])
        if hits:
            md5 = hits[0]["_source"].get("md5")
            if md5:
                objects = client.list_objects(
                    MINIO_RAW_BUCKET, prefix=f"{md5}/", recursive=True
                )
                for obj in objects:
                    if not obj.object_name.endswith(".pdf"):
                        continue
                    return client.presigned_get_object(
                        MINIO_RAW_BUCKET,
                        obj.object_name,
                        expires=timedelta(hours=1),
                    )
    except Exception:
        pass

    return None


def _build_pdf_response(task):
    """构建 PDF 预签名 URL"""
    from datetime import timedelta

    from src.config import MINIO_RAW_BUCKET
    from src.minio_client import get_minio

    client = get_minio()
    if task.raw_minio_path.startswith(f"{MINIO_RAW_BUCKET}/"):
        object_path = task.raw_minio_path[len(f"{MINIO_RAW_BUCKET}/"):]
    else:
        object_path = task.raw_minio_path

    presigned = client.presigned_get_object(
        MINIO_RAW_BUCKET,
        object_path,
        expires=timedelta(hours=1),
    )
    return {
        "pdf_url": presigned,
        "total_pages": 0,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/tokens/usage")
async def token_usage(_admin=Depends(require_admin)):
    """查看各 Token 当日额度用量（admin only）"""
    mgr = get_key_manager()
    return {
        "tokens": await mgr.usage_report(),
        "exhausted": await mgr.is_exhausted(),
        "all_exhausted": await mgr.is_exhausted(),
    }
