"""FastAPI 网关 — 多 Key 额度管理 + 自动轮换"""

import hashlib
import traceback
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, UploadFile
from sqlalchemy import select

from src.config import CHUNK_SIZE, MINIO_RAW_BUCKET, MINERU_BATCH_SIZE
from src.db import async_session, engine
from src.key_manager import TokenExhausted, get_key_manager
from src.mineru_client import submit_batch
from src.minio_client import check_parsed_exists, init_buckets, upload_raw_pdf
from src.models import Base, DocumentTask, TaskStatus
from src.redis_client import enqueue_batch
from src.schemas import TaskCreateResponse, TaskStatusResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_buckets()
    # 预热 KeyManager
    print("[API] KeyManager 启动:")
    print(get_key_manager().usage_report())
    yield


app = FastAPI(title="MinerU Pipeline - Phase 1", version="1.0", lifespan=lifespan)


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

async def _handle_one_file(file, session) -> tuple[TaskCreateResponse, dict | None]:
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
        if existing.status == TaskStatus.PARSED and check_parsed_exists(file_md5):
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
    raw_path = upload_raw_pdf(file_md5, filename, content)
    task = DocumentTask(
        md5=file_md5, original_name=filename,
        raw_minio_path=f"{MINIO_RAW_BUCKET}/{raw_path}",
        status=TaskStatus.PENDING,
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
async def upload_documents_batch(files: list[UploadFile] = File(...)):
    if len(files) > CHUNK_SIZE:
        raise HTTPException(400, f"单次最多 {CHUNK_SIZE} 个文件")

    responses = []
    to_submit = []

    async with async_session() as session:
        for file in files:
            resp, fi = await _handle_one_file(file, session)
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
