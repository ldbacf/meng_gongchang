"""FastAPI 网关 — 文件上传入口，MD5 去重，调度 MinerU 解析"""

import hashlib
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from sqlalchemy import select

from src.config import CHUNK_SIZE, MINIO_RAW_BUCKET
from src.db import async_session, engine
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
    yield


app = FastAPI(title="MinerU Pipeline - Phase 1", version="1.0", lifespan=lifespan)


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


async def _submit_and_enqueue(
    file_infos: list[dict],
    session,
) -> str:
    """提交 MinerU + 推入 Redis，返回 batch_id"""
    batch_id, md5_list = await submit_batch(file_infos)
    for fi in file_infos:
        stmt = select(DocumentTask).where(DocumentTask.md5 == fi["md5"])
        r = await session.execute(stmt)
        t = r.scalar_one_or_none()
        if t:
            t.batch_id = batch_id
            t.status = TaskStatus.PROCESSING
    await session.commit()
    await enqueue_batch(batch_id, md5_list)
    return batch_id


async def _handle_one_file(file, session) -> tuple[TaskCreateResponse, dict | None]:
    """
    处理单个文件: MD5 查重 + MinIO 验证。
    返回 (response, file_info_for_mineru_or_None)。
    """
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

    # ── 已存在 → 三要素验证：DB 记录 + status=parsed + MinIO 真有 full.md ──
    if existing:
        if existing.status == TaskStatus.PARSED and check_parsed_exists(file_md5):
            return TaskCreateResponse(
                id=existing.id,
                md5=existing.md5,
                original_name=existing.original_name,
                status=existing.status,
                raw_minio_path=existing.raw_minio_path,
                message="秒传: 解析产物已存在",
            ), None

        # 记录存在但解析未完成/失败/丢失 → 重试解析
        resp = TaskCreateResponse(
            id=existing.id,
            md5=existing.md5,
            original_name=existing.original_name,
            status=TaskStatus.PENDING,
            raw_minio_path=existing.raw_minio_path,
            message="重试: 重新提交解析",
        )
        # 更新状态以触发重试
        existing.status = TaskStatus.PENDING
        existing.error_msg = None
        await session.commit()
        return resp, {"name": filename, "data": content, "md5": file_md5}

    # ── 新文件 → 存 raw-docs + 写 DB ──
    raw_path = upload_raw_pdf(file_md5, filename, content)
    task = DocumentTask(
        md5=file_md5,
        original_name=filename,
        raw_minio_path=f"{MINIO_RAW_BUCKET}/{raw_path}",
        status=TaskStatus.PENDING,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    return TaskCreateResponse(
        id=task.id,
        md5=task.md5,
        original_name=task.original_name,
        status=task.status,
        raw_minio_path=task.raw_minio_path,
        message="新文件: 待提交解析",
    ), {"name": filename, "data": content, "md5": file_md5}


@app.post("/api/v1/documents", response_model=TaskCreateResponse)
async def upload_document(file: UploadFile = File(...)):
    """单文件上传"""
    async with async_session() as session:
        resp, fi = await _handle_one_file(file, session)

        if fi is None:
            return resp  # 秒传

        try:
            await _submit_and_enqueue([fi], session)
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
    """批量上传 — 最多 50 个文件"""
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

    # 批量提交 MinerU
    if to_submit:
        try:
            async with async_session() as session:
                await _submit_and_enqueue(to_submit, session)
            for resp in responses:
                if resp.status == TaskStatus.PENDING:
                    resp.status = TaskStatus.PROCESSING
                    resp.message = "已提交解析任务"
        except Exception as e:
            traceback.print_exc()
            print(f"[API] MinerU 提交失败: {e}")
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
    """按 ID 查询文档状态"""
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.id == doc_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


@app.get("/api/v1/documents/md5/{md5}", response_model=TaskStatusResponse)
async def get_document_by_md5(md5: str):
    """按 MD5 查询文档状态"""
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
