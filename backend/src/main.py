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

from src.config import CHUNK_SIZE, CORS_ORIGINS, MINIO_RAW_BUCKET, MINERU_BATCH_SIZE
from src.db import async_session, engine
from src.key_manager import TokenExhausted, get_key_manager
from src.mineru_client import submit_batch
from src.minio_client import check_parsed_exists, get_minio, init_buckets, upload_raw_pdf
from src.models import Base, DocumentTask, TaskStatus
from src.redis_client import enqueue_batch
from src.schemas import TaskCreateResponse, TaskStatusResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Manual migration: add kb_id column to existing document_tasks
        await conn.run_sync(lambda c: c.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE document_tasks ADD COLUMN IF NOT EXISTS "
                "kb_id UUID"
            )
        ))
        await conn.run_sync(lambda c: c.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE document_tasks ADD COLUMN IF NOT EXISTS "
                "pipeline_steps JSONB"
            )
        ))
    await init_buckets()

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
                slug="zhong_guo_quan_ke",
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

    # 预热 bge-m3 嵌入模型（启动时加载一次，后续常驻内存）
    from src.llm import get_embedding_model
    get_embedding_model()
    print("[API] bge-m3 模型加载完成")
    # 预热 KeyManager
    print("[API] KeyManager 启动:")
    print(get_key_manager().usage_report())

    # 启动后台 Worker（MinerU 轮询 + 索引管线）
    import asyncio
    from src.worker import run_worker_background
    _worker_stop = asyncio.Event()
    _worker_task = asyncio.create_task(run_worker_background(_worker_stop))

    yield

    _worker_stop.set()
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass


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
    核心: 按 KeyManager 分配 token，每 10 个一批提交 MinerU。

    to_submit: [{"name": "...", "data": b"...", "md5": "..."}]
    """
    key_mgr = get_key_manager()
    # {token: [{"name": ..., "data": ..., "md5": ..., "pages": N}, ...]}
    groups: dict[str, list[dict]] = defaultdict(list)
    sorted_files = []

    # 读页数 + 分配 key
    for fi in to_submit:
        pages = _pdf_pages(fi["data"])
        fi["pages"] = pages
        sorted_files.append(fi)

    # 大文件优先处理 (减少碎片)
    sorted_files.sort(key=lambda x: x["pages"], reverse=True)

    # 先按 pages 排序，再逐个分配 token
    # 分配时检查剩余容量，放不下就换 key
    key_to_stash: dict[str, list[dict]] = defaultdict(list)  # 先暂存到各自 key

    for fi in sorted_files:
        pages = fi["pages"]
        try:
            token = key_mgr.acquire(pages)
            key_to_stash[token].append(fi)
            key_mgr.release(token, pages)  # 预占额度
        except TokenExhausted as e:
            print(f"[API] {e}")
            # 把未分配的标为失败
            for failed_md5 in [fi["md5"]]:
                stmt = select(DocumentTask).where(DocumentTask.md5 == failed_md5)
                r = await session.execute(stmt)
                t = r.scalar_one_or_none()
                if t:
                    t.status = TaskStatus.FAILED
                    t.error_msg = f"所有 Key 额度用完: {e}"
            await session.commit()
            continue

    # 每个 key 的文件分成 10 个一批提交
    for token, files in key_to_stash.items():
        for i in range(0, len(files), MINERU_BATCH_SIZE):
            chunk = files[i:i + MINERU_BATCH_SIZE]
            chunk_pages = sum(f["pages"] for f in chunk)
            print(f"[API] 提交 {len(chunk)} 个文件 "
                  f"(token={token[:8]}..., 共{chunk_pages}页)")

            try:
                batch_id, md5_list = await submit_batch(chunk, token=token)
                for fi in chunk:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
                    r = await session.execute(stmt)
                    t = r.scalar_one_or_none()
                    if t:
                        t.batch_id = batch_id
                        t.status = TaskStatus.PROCESSING
                await session.commit()
                await enqueue_batch(batch_id, md5_list, token=token)
                print(f"  [API] 完成 -> batch_id={batch_id}")
            except Exception as e:
                traceback.print_exc()
                print(f"[API] 批次提交失败: {e}")
                for fi in chunk:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
                    r = await session.execute(stmt)
                    t = r.scalar_one_or_none()
                    if t:
                        t.status = TaskStatus.FAILED
                        t.error_msg = str(e)
                await session.commit()


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
        if kb_id:
            existing.kb_id = kb_id
        if existing.status == TaskStatus.PARSED and check_parsed_exists(file_md5):
            await session.commit()
            return TaskCreateResponse(
                id=existing.id, md5=existing.md5,
                original_name=existing.original_name,
                status=existing.status,
                raw_minio_path=existing.raw_minio_path,
                message="秒传: 解析产物已存在",
            ), None

        existing.status = TaskStatus.PENDING
        existing.error_msg = None
        await session.commit()
        return TaskCreateResponse(
            id=existing.id, md5=existing.md5,
            original_name=existing.original_name,
            status=TaskStatus.PENDING,
            raw_minio_path=existing.raw_minio_path,
            message="重试: 重新提交解析",
        ), {"name": filename, "data": content, "md5": file_md5}

    # 新文件
    from datetime import datetime as _dt, timezone as _tz
    from src.models import default_pipeline_steps

    raw_path = upload_raw_pdf(file_md5, filename, content)
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "done", "ts": _dt.now(_tz.utc).isoformat()}
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

from src.auth import get_current_user  # noqa: E402
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
async def upload_document(file: UploadFile = File(...)):
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
                t.status = TaskStatus.FAILED
                t.error_msg = str(e)
                await session.commit()

        return resp


@app.post("/api/v1/documents/batch", response_model=list[TaskCreateResponse])
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    kb_id: str | None = Query(None),
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
                        t.status = TaskStatus.FAILED
                        t.error_msg = str(e)
                await session.commit()
            for resp in responses:
                if resp.status == TaskStatus.PENDING:
                    resp.status = TaskStatus.FAILED
                    resp.message = f"提交失败: {e}"

    return responses


@app.get("/api/v1/documents/{doc_id}", response_model=TaskStatusResponse)
async def get_document_status(doc_id: uuid.UUID):
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.id == doc_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


@app.get("/api/v1/documents/md5/{md5}", response_model=TaskStatusResponse)
async def get_document_by_md5(md5: str):
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
        from src.search import _get_es

        es = _get_es()
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
        from src.search import _get_es

        es = _get_es()

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
async def token_usage():
    """查看各 Token 当日额度用量"""
    mgr = get_key_manager()
    return {
        "tokens": mgr.usage_report(),
        "exhausted": mgr.is_exhausted(),
        "all_exhausted": mgr.is_exhausted(),
    }
