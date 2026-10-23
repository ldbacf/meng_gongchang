"""文档路由 — 上传 / 批量上传 / 状态查询 / PDF 流。

从 `main.py` 拆出（原先 7 个端点连同 PDF Range 解析、MinIO 反查、跨 KB 复制等
业务逻辑都堆在装配文件里，共约 400 行，与 `chat.py` / `admin.py` 的既有模式不一致）。

保留的兼容入口：`app.main` 仍 re-export `_handle_one_file` / `_copy_across_kb` /
`_pdf_range_bounds` / `_find_pdf_object_name`，避免既有测试与 admin 路由的导入断裂；
新代码请直接从本模块导入。
"""
from __future__ import annotations

import hashlib
import re
import traceback
import uuid as _uuid

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from app.infrastructure.container import get_container
from app.infrastructure.db.models import DocumentTask, TaskStatus
from app.infrastructure.db.session import async_session
from app.infrastructure.settings import get_settings
from app.interface.schemas import TaskCreateResponse, TaskStatusResponse
from app.interface.security import get_current_user, require_admin

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_MAX_UPLOAD_BYTES = 200 * 1024 * 1024


# ── 小工具 ────────────────────────────────────────────────────


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _pdf_pages(data: bytes) -> int:
    """读取 PDF 页数。"""
    doc = fitz.open(stream=data, filetype="pdf")
    pages = doc.page_count
    doc.close()
    return pages


# ── 多 Key 提交逻辑 ───────────────────────────────────────────


async def _submit_batches(to_submit: list[dict], session) -> None:
    """提交批次到 MinerU — 统一经 SubmissionService（O-3.5，收敛双入口）。

    to_submit: [{"name": "...", "data": b"...", "md5": "..."}]
    """
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


async def _handle_one_file(
    file, session, kb_id=None
) -> tuple[TaskCreateResponse, dict | None]:
    filename = file.filename or "unknown"
    content = await file.read()
    if not content:
        raise HTTPException(400, f"{filename} 为空")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"{filename} 超过 200MB")

    file_md5 = _md5(content)

    minio = get_container().get_minio()

    stmt = select(DocumentTask).where(DocumentTask.md5 == file_md5)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # O-3.7：禁止 reassign kb_id（归属漂移）——跨 KB 重传复制新 task（保留 parsed 引用）
        if kb_id and existing.kb_id != kb_id:
            return await _copy_across_kb(
                existing, file_md5, filename, content, kb_id, session
            )
        if existing.status == TaskStatus.PARSED and minio.check_parsed_exists(file_md5):
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

    # ── 新文件：落 raw-docs + 建 task（提交解析由调用方经 SubmissionService 完成）──
    from datetime import datetime as _dt, timezone as _tz

    from app.infrastructure.db.models import default_pipeline_steps

    raw_path = minio.upload_raw_pdf(file_md5, filename, content)
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "done", "ts": _dt.now(_tz.utc).timestamp()}  # ts 统一 float
    task = DocumentTask(
        kb_id=kb_id,
        md5=file_md5, original_name=filename,
        raw_minio_path=f"{get_settings().minio_raw_bucket}/{raw_path}",
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


async def _copy_across_kb(
    existing, file_md5: str, filename: str, content: bytes, kb_id, session,
) -> tuple[TaskCreateResponse, dict | None]:
    """跨 KB 重传（O-3.7）：复制新 task 到目标 KB，保留 parsed 引用，不 reassign 原 task。

    - 已解析（parsed_minio_path 存在）：新 task 置 PARSED + 发 resume 队列消息
      （batch_id=新 task.id，worker 从 checkpoint 续跑直接重索引到新 KB）。
    - 未解析：新 task 置 PENDING，返回 fi 由调用方重新提交解析。
    """
    from datetime import datetime as _dt, timezone as _tz

    from app.infrastructure.db.models import default_pipeline_steps

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


# ── 端点 ──────────────────────────────────────────────────────


@router.post("", response_model=TaskCreateResponse)
async def upload_document(
    file: UploadFile = File(...),
    _admin=Depends(require_admin),
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


@router.post("/batch", response_model=list[TaskCreateResponse])
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    kb_id: str | None = Query(None),
    _admin=Depends(require_admin),
):
    _max_files = get_settings().max_upload_files
    if len(files) > _max_files:
        raise HTTPException(400, f"单次最多 {_max_files} 个文件")

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


@router.get("/md5/{md5}", response_model=TaskStatusResponse)
async def get_document_by_md5(
    md5: str,
    _user=Depends(get_current_user),
):
    """按 md5 查文档状态。

    路径声明必须在 `/{doc_id}` 之前，否则 `md5` 会被 doc_id（uuid）吃掉。
    """
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


@router.get("/{doc_id}/pdf/stream")
async def stream_document_pdf(
    doc_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    """代理 PDF 内容流（支持 Range 断点，T-5.6）。

    从 MinIO 读取 PDF 直接流式返回（不再暴露 presigned URL）。`Range: bytes=x-y`
    → `206 Partial Content` + `Content-Range`；越界 → 416；无 Range → 200 全量。
    """
    bucket = get_settings().minio_raw_bucket
    client = get_container().get_minio().client
    object_path = await _find_pdf_object_name(doc_id)
    if not object_path:
        raise HTTPException(404, f"文档不存在: {doc_id}")

    try:
        stat = client.stat_object(bucket, object_path)
    except Exception as e:
        raise HTTPException(502, f"读取 PDF 失败: {e}")
    total = stat.size

    headers = {
        "Content-Disposition": f'inline; filename="{doc_id}.pdf"',
        "Cache-Control": "public, max-age=3600",
        "Accept-Ranges": "bytes",
    }

    range_header = request.headers.get("range", "")
    offset, length, range_status, range_headers = _pdf_range_bounds(range_header, total)
    if range_status == 416:
        return Response(status_code=416, headers=range_headers)
    status_code = range_status
    headers.update(range_headers)

    try:
        response = client.get_object(bucket, object_path, offset=offset, length=length)
    except Exception as e:
        raise HTTPException(502, f"读取 PDF 失败: {e}")

    if status_code == 206:
        headers["Content-Length"] = str(length)

    return StreamingResponse(
        response.stream(amt=65536),
        media_type="application/pdf",
        status_code=status_code,
        headers=headers,
    )


@router.get("/{doc_id}", response_model=TaskStatusResponse)
async def get_document_status(
    doc_id: _uuid.UUID,
    _user=Depends(get_current_user),
):
    async with async_session() as session:
        stmt = select(DocumentTask).where(DocumentTask.id == doc_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(404, "文档不存在")
        return task


# ── PDF Range 解析 / MinIO 反查 ───────────────────────────────


def _pdf_range_bounds(range_header: str, total: int) -> tuple[int, int, int, dict]:
    """解析 `Range: bytes=x-y` → `(offset, length, status_code, range_headers)`（T-5.6）。

    - 无/非法 Range → 200 全量。
    - `bytes=x-y` → 206 + `Content-Range: bytes x-y/total`（含 open-ended 上下界，len > total 截断）。
    - `start >= total` → 416。
    """
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m or total <= 0:
        return 0, total, 200, {}
    start_s, end_s = m.group(1), m.group(2)
    if not start_s and not end_s:
        return 0, total, 200, {}
    if not start_s:
        # suffix：bytes=-N → 最后 N 字节
        n = min(int(end_s), total)
        start = total - n
        end = total - 1
        return start, n, 206, {
            "Content-Range": f"bytes {start}-{end}/{total}",
        }
    start = int(start_s)
    end = int(end_s) if end_s else total - 1
    if start >= total:
        return 0, 0, 416, {"Content-Range": f"bytes */{total}"}
    end = min(end, total - 1)
    return start, end - start + 1, 206, {
        "Content-Range": f"bytes {start}-{end}/{total}",
    }


async def _find_pdf_object_name(doc_id: str) -> str | None:
    """查找 PDF 在 MinIO raw-docs 桶中的对象路径。

    按优先级:
    1. DocumentTask 表（通过 id / md5 / batch_id）
    2. 直接扫 MinIO raw-docs 前缀
    3. ES 反查 md5 再扫 MinIO
    """
    from app.infrastructure.db.session import async_session

    bucket = get_settings().minio_raw_bucket
    es_index = get_settings().es_index
    client = get_container().get_minio().client

    # ── 1. 先查 DocumentTask 表 ──
    async with async_session() as session:
        task = None
        try:
            uid = _uuid.UUID(doc_id)
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
            if task.raw_minio_path.startswith(f"{bucket}/"):
                return task.raw_minio_path[len(f"{bucket}/"):]
            return task.raw_minio_path

    # ── 2. 直接按 doc_id 前缀扫 MinIO ──
    for prefix in (f"{doc_id}/", doc_id):
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            if obj.object_name.endswith(".pdf"):
                return obj.object_name

    # ── 3. 查 ES L0 chunk 反拿 md5 → 再去 MinIO 扫 ──
    try:
        from app.infrastructure.search import get_es_client

        es = get_es_client()
        resp = es.search(
            index=es_index,
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
                    bucket, prefix=f"{md5}/", recursive=True
                )
                for obj in objects:
                    if obj.object_name.endswith(".pdf"):
                        return obj.object_name
    except Exception:
        pass

    return None
