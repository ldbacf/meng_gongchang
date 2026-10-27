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
from functools import lru_cache

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from app.infrastructure.container import get_container
from app.infrastructure.db.models import DocumentTask, TaskStatus
from app.infrastructure.db.session import async_session
from app.infrastructure.settings import get_settings
from app.interface.schemas import (
    AbstractSectionSchema,
    CitationBox,
    CitationLocateResponse,
    EvidencePassage,
    EvidenceResponse,
    SampleSizeSchema,
    TaskCreateResponse,
    TaskStatusResponse,
)
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


@router.head("/{doc_id}/pdf/stream", name="stream_document_pdf_head")
@router.get("/{doc_id}/pdf/stream", name="stream_document_pdf")
async def stream_document_pdf(
    doc_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    """代理 PDF 内容流（支持 Range 断点，T-5.6）。

    从 MinIO 读取 PDF 直接流式返回（不再暴露 presigned URL）。`Range: bytes=x-y`
    → `206 Partial Content` + `Content-Range`；越界 → 416；无 Range → 200 全量。

    **同时支持 HEAD**：pdf.js 会先用 HEAD 探测 `Content-Length` 与 `Accept-Ranges`，
    再决定是否分片拉取。只声明 GET 时 HEAD 会 405，pdf.js 就退回"整份下载"，
    分片加载失效（前端表现为要等整份 PDF 到齐才开始渲染）。

    **HEAD 单独一个装饰器**（而不是 `api_route(methods=["GET","HEAD"])`）：
    FastAPI 的默认 `generate_unique_id` 只用 `route.methods` 里的**第一个**方法名
    拼 operationId，一条路由挂两个方法会让 GET/HEAD 的 ID 完全相同。
    OpenAPI 里出现重复 operationId → `openapi-typescript` 生成的类型直接
    TS2300（重复标识符），整个前端类型检查失败。拆开后函数体仍只写一份。
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
    # 长度在 HEAD 与 206 两种情况下都要显式给出（pdf.js 据此分片）
    headers["Content-Length"] = str(length)

    if request.method == "HEAD":
        # 只回头，不读 MinIO、不建流；content-type 也要给（pdf.js 会校验）
        return Response(
            status_code=status_code,
            headers=headers,
            media_type="application/pdf",
        )

    try:
        response = client.get_object(bucket, object_path, offset=offset, length=length)
    except Exception as e:
        raise HTTPException(502, f"读取 PDF 失败: {e}")

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

    按**代价从低到高**排序（这是性能关键，见下方说明）:
    1. DocumentTask 表（id / md5 / batch_id 三个索引查询，各约 5-137ms）
    2. ES L0 chunk 反查 md5（约 10ms）
    3. 最后才扫 MinIO

    **为什么 ES 必须排在 MinIO 扫描之前**：
    `doc_id` 有两种形态 —— DocumentTask 的 uuid，或**预置文献的 ES 文章编号**
    （如 "7707"）。后者在 DocumentTask 里查不到（md5/batch_id 都对不上），
    旧实现会先执行「按 doc_id 前缀扫 raw-docs」这一步；而 raw-docs 有 1256 个
    对象，MinIO 又跑在 Windows bind mount 上（240 KB/s），
    **实测这一步耗时 21.9 秒** —— 每次点引用都要等这么久。

    而 ES 反查只要 10ms 就能拿到 md5，再由 md5 直接命中 raw-docs 的对象路径，
    根本不需要扫桶。调整顺序后首次定位从 21.9s 降到约 0.6s。
    """
    from app.infrastructure.db.session import async_session

    bucket = get_settings().minio_raw_bucket
    es_index = get_settings().es_index
    client = get_container().get_minio().client

    # ── 1. DocumentTask 表（三种键，都是索引查询）──
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

    # ── 2. ES 反查 md5 → 用 md5 前缀精确取对象（不扫全桶）──
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
                # raw-docs 的对象名形如 {md5}/{filename}.pdf，按 md5 前缀查很快
                for obj in client.list_objects(bucket, prefix=f"{md5}/", recursive=True):
                    if obj.object_name.endswith(".pdf"):
                        return obj.object_name
    except Exception:
        pass

    # ── 3. 兜底：按 doc_id 前缀扫（慢，1256 对象 × 240 KB/s 约 20s，尽量别走到）──
    for prefix in (f"{doc_id}/", doc_id):
        try:
            for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                if obj.object_name.endswith(".pdf"):
                    return obj.object_name
        except Exception:
            continue

    return None

# ── 引用定位：MinerU content_list 的 bbox ─────────────────────
#
# 为什么要这个端点：
# 原实现用 pdf.js 的 findController 在文本层里搜 snippet。两个致命问题：
#   1. 必须先加载完整个 PDF（2.76MB @ 240KB/s ≈ 12s）才可能搜到
#   2. MinerU 抽取的文本与 PDF 文本层在标点/空格/连字上并不一致，
#      稍长一点就 0 命中，前端只能显示「未定位到原文」
#
# 而 MinerU 在 parsed-data/{md5}/*_content_list.json 里已经给出了每条文本的
# **精确坐标**：{"text": ..., "bbox": [x0,y0,x1,y1], "page_idx": 0}，
# bbox 是相对页面宽高的 0-1000 归一化值。直接拿它画框，既不用等全文、
# 也不受文本差异影响。
#
# 关联链：ES chunk.md5 → parsed-data/{md5}/ → content_list.json


def _norm_for_match(s: str) -> str:
    """归一化文本用于匹配。

    去掉所有空白与常见标点，只保留中英文数字 —— 这样 MinerU 文本与
    ES chunk 文本在标点上的差异不会影响匹配。实测 pdf 里是全角「，」
    而 chunk 里可能是半角，直接比会失败。
    """
    import re as _re

    return _re.sub(r"[\s，。、；：！？""''（）()《》〈〉【】\[\]…—\-–·,.;:!?\"'`]+", "", s or "")


def _find_content_list_object(client, md5: str) -> str | None:
    """在 parsed-data/{md5}/ 下找 content_list.json。"""
    parsed_bucket = get_settings().minio_parsed_bucket
    try:
        for obj in client.list_objects(parsed_bucket, prefix=f"{md5}/", recursive=True):
            if obj.object_name.endswith("_content_list.json"):
                return obj.object_name
    except Exception:
        return None
    return None


# ── content_list 缓存 ─────────────────────────────────────────
#
# 为什么必须缓存：content_list.json 有 100+ KB，而 MinIO 走的是 Windows
# bind mount（约 240 KB/s）。实测**不缓存时单次 locate 要 21.8 秒** ——
# 用户点个引用要等 20 秒才看到高亮，完全不可用。
#
# 缓存后同一篇文档的后续定位是毫秒级。用模块级 LRU：
#   - 数据是 MinerU 的**解析产物**，文档不改就不会变，可以放心缓存
#   - maxsize=64：一篇约 100KB 解析后约 1MB 内存，64 篇约 64MB 上限
#   - 重新上传/重解析同一份文档时 md5 不变但内容可能变 —— 这是已知的
#     可接受偏差（服务重启即失效；且重解析会换 content_list 的对象名，
#     严格来说应把对象名也纳入 key，见下方 _load 的实现）
@lru_cache(maxsize=64)
def _load_content_list_cached(md5: str, object_name: str) -> tuple[dict, ...]:
    """读取并解析 content_list.json（按对象名缓存，重解析后对象名变化会自动失效）。"""
    from app.infrastructure.container import get_container

    client = get_container().get_minio().client
    raw = client.get_object(get_settings().minio_parsed_bucket, object_name).read()
    import json as _json

    items = _json.loads(raw)
    if not isinstance(items, list):
        return ()
    # 转成不可变 tuple，避免调用方误改缓存内容
    return tuple(items)


@lru_cache(maxsize=128)
def _content_list_object_name(md5: str) -> str | None:
    """md5 → content_list.json 的对象名（带缓存）。

    不缓存的话每次都要 `list_objects`（一次 MinIO 往返），在 240 KB/s 的
    链路上同样是秒级开销。对象名对同一份 md5 是稳定的，可以安全缓存。
    """
    from app.infrastructure.container import get_container

    client = get_container().get_minio().client
    return _find_content_list_object(client, md5)


def _load_content_list(client, md5: str) -> list[dict]:
    """取 content_list 条目（对象名与内容都带缓存）。"""
    obj = _content_list_object_name(md5)
    if not obj:
        return []
    try:
        return list(_load_content_list_cached(md5, obj))
    except Exception:
        return []


def _locate_in_content_list(items: list[dict], snippet: str) -> list[CitationBox]:
    """在 content_list 条目里定位 snippet，返回命中的 bbox（按相关度排序）。

    匹配策略：把 snippet 与每个条目都归一化后做双向包含 + 最长公共子串判断。
    - 条目文本 ⊂ snippet（引用跨了多个块）：算命中
    - snippet ⊂ 条目文本（引用是某块的一部分）：算命中
    - 公共子串 ≥ 阈值：兜底（容忍局部差异）

    **按相关度排序**：同一句话常在标题、摘要、正文、结论里各出现一次
    （实测一个片段命中 5 处）。引用要的是「它在正文里被引用的那一处」，
    标题/参考文献列表里的重复命中是噪声。排序规则：
      1. 完整包含优先（`target in nt` > 部分匹配）
      2. 文本越长越可能是正文段落（标题短、页眉页脚更短）
      3. 页码靠后的优先级降低（参考文献通常在最后的页）
    """
    target = _norm_for_match(snippet)
    if not target:
        return []

    scored: list[tuple[float, CitationBox]] = []
    for it in items:
        text = it.get("text") or ""
        nt = _norm_for_match(text)
        if not nt:
            continue

        bbox = it.get("bbox")
        page = it.get("page_idx")
        if bbox is None or page is None or len(bbox) != 4:
            continue

        # 纯页码 / 页眉页脚不参与定位
        if it.get("type") in ("page_number",):
            continue

        # 命中判定分三种情况，阈值不同：
        #
        # a) snippet ⊂ 条目（引用是某块的一部分，最常见）→ 直接算命中
        # b) 条目 ⊂ snippet（引用跨了多个块）→ **不设长度下限**
        #    跨块时单个条目往往很短（「一线药物包括ACEI」只有 8 个字），
        #    若沿用全局 12 字阈值会全部漏掉，这是本函数最初的真实 bug。
        #    条件是条目足够长（≥4 字）且未因「太短」而被当作噪声。
        # c) 部分重叠 → 用长度阈值兜底，容忍局部差异
        contained = target in nt
        sub_block = len(nt) >= 4 and nt in target
        overlap = _longest_common(target, nt)

        if not contained and not sub_block and overlap < min(12, max(6, len(target) // 2)):
            continue

        score = 0.0
        if contained:
            score += 1000
        score += overlap
        # 正文段落通常较长；标题/参考文献都很短
        score += min(len(nt), 400) * 0.5
        # 参考文献类条目降权
        if it.get("type") == "ref_text" or nt.startswith("引用本文"):
            score -= 800
        # 页尾/页首的重复（通常是页眉页脚）轻降权
        y0 = float(bbox[1])
        if y0 < 60 or y0 > 940:
            score -= 300

        scored.append((score, CitationBox(
            page=int(page) + 1, bbox=[float(v) for v in bbox], text=text[:200]
        )))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [box for _s, box in scored[:4]]


def _longest_common(a: str, b: str) -> int:
    """最长公共子串长度（只用于判断是否值得算命中）。

    规模控制：两边都截到 120 字符，且一旦命中 20 字就提前返回。
    实测 112 条 × (86,93) 字符共约 1ms，可接受。
    不截断的话，异常长的 snippet（比如整段摘要）会退化成 O(n²) 卡住请求。
    """
    if not a or not b:
        return 0
    a = a[:120]
    b = b[:120]
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > best:
                best = k
                if best >= 20:
                    return best
    return best


@router.get("/{doc_id}/locate", response_model=CitationLocateResponse)
async def locate_citation(
    doc_id: str,
    snippet: str = Query(..., min_length=2, description="引用原文片段"),
    _user=Depends(get_current_user),
):
    """定位引用片段在 PDF 中的位置（页码 + bbox）。

    数据来自 MinerU 的 content_list.json（见本段开头说明）。
    找不到时返回 `found=false`，前端应回退到「只显示摘录卡」而不是报错。
    """
    import json as _json

    client = get_container().get_minio().client

    # 1) 拿 md5（与 /pdf/stream 同一条查找逻辑，保证指向同一份文件）
    object_path = await _find_pdf_object_name(doc_id)
    md5 = None
    if object_path:
        # raw-docs/{md5}/{filename}.pdf  → 取 md5
        parts = object_path.split("/")
        if parts:
            md5 = parts[0]

    if not md5:
        # 退回用 ES 反查
        try:
            from app.infrastructure.search import get_es_client

            es = get_es_client()
            resp = es.search(
                index=get_settings().es_index,
                body={
                    "size": 1,
                    "query": {"bool": {"must": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"level": "L0"}},
                    ]}},
                    "_source": ["md5"],
                },
            )
            hits = resp.get("hits", {}).get("hits", [])
            if hits:
                md5 = hits[0]["_source"].get("md5")
        except Exception:
            pass

    if not md5:
        return CitationLocateResponse(found=False, message="未找到该文档的解析记录")

    # 2) 读 content_list.json（带 LRU 缓存 —— 不缓存单次要 21.8s，见 _load_content_list_cached）
    items = _load_content_list(client, md5)
    if not items:
        return CitationLocateResponse(
            found=False, md5=md5, message="该文档没有解析坐标（content_list.json 缺失）"
        )

    boxes = _locate_in_content_list(items, snippet)
    total_pages = 1 + max(
        (int(i.get("page_idx", 0)) for i in items if i.get("page_idx") is not None),
        default=0,
    )

    if not boxes:
        return CitationLocateResponse(
            found=False, total_pages=total_pages, md5=md5,
            message="未在解析结果中找到该片段",
        )

    return CitationLocateResponse(
        found=True, boxes=boxes, total_pages=total_pages, md5=md5,
        message=f"命中 {len(boxes)} 处",
    )


# ── 证据卡 ────────────────────────────────────────────────────
#
# 与 /locate 的差别见 schemas.EvidenceResponse 的说明。
# 数据来源与 /locate 完全一致（doc-meta 摘要 + ES L0 元信息 + ES L1 命中块），
# 所以复用 `_find_pdf_object_name` 拿 md5，不再写第二套查找逻辑。


def _es_l0_source(doc_id: str) -> dict:
    """取该文献的 L0 chunk（期刊元信息）。失败返回空 dict。"""
    try:
        from app.infrastructure.search import get_es_client

        resp = get_es_client().search(
            index=get_settings().es_index,
            body={
                "size": 1,
                "query": {"bool": {"must": [
                    {"term": {"doc_id": doc_id}},
                    {"term": {"level": "L0"}},
                ]}},
                "_source": [
                    "doc_id", "md5", "title_cn", "title_en", "journal", "source",
                    "article_type", "doi", "authors_cn", "keywords_cn", "content",
                ],
            },
        )
        hits = resp.get("hits", {}).get("hits", [])
        return hits[0]["_source"] if hits else {}
    except Exception:
        return {}


def _load_doc_meta_json(md5: str | None) -> dict:
    """读 doc-meta/{md5}/*.json（结构式摘要在这里，L0 chunk 里只有拼接后的文本）。"""
    if not md5:
        return {}
    try:
        import json as _json

        client = get_container().get_minio().client
        bucket = get_settings().minio_meta_bucket
        for obj in client.list_objects(bucket, prefix=f"{md5}/", recursive=True):
            if obj.object_name.endswith(".json"):
                raw = client.get_object(bucket, obj.object_name).read()
                data = _json.loads(raw.decode("utf-8", errors="replace"))
                return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _extract_abstract_from_l0(content: str) -> str:
    """L0 chunk 的 content 里摘要在 `【摘要】` 与 `【关键词】` 之间。

    只在 doc-meta 缺失时兜底 —— doc-meta 的 `abstract_cn` 才是原始字段。
    """
    if not content:
        return ""
    m = re.search(r"【摘要】\s*(.*?)(?=【关键词】|$)", content, re.S)
    return m.group(1).strip() if m else ""


def _load_doc_l1_chunks(doc_id: str) -> list[dict]:
    """取该文档全部 L1 块（按 `_doc` 顺序）。

    一次查询同时解决「命中块」与「前后文」两个需求，不用三次往返。

    为什么不直接用 ES 的 `match_phrase` 定位命中块：
    **引用片段不是干净的原文**。`citation.snippet` 是 `hit.content[:200]`，
    带 `【章节】…` 前缀、可能截断在词中间；而证据卡展示用的是清洗后的文本
    （去了前缀、洗了 LaTeX）。实测拿清洗后的句子去 match_phrase 原 chunk
    **一条都命中不了**，静默回退到该文档第一个正文块 —— 用户点「2.4 结果」
    却看到「1.1 研究对象」，这是比不定位更糟的错误答案。

    所以改成：把整篇块拉回来，在 Python 里用与 /locate 同一套归一化
    做包含匹配。单篇 17~49 块、每块 ≤ 2KB，一次 400 条查询足够。
    """
    try:
        from app.infrastructure.search import get_es_client

        resp = get_es_client().search(
            index=get_settings().es_index,
            body={
                "size": 400,
                "query": {"bool": {"filter": [
                    {"term": {"level": "L1"}},
                    {"term": {"doc_id": doc_id}},
                ]}},
                "_source": ["chunk_id", "heading_stack", "content", "heading_depth"],
                "sort": ["_doc"],
            },
        )
        return [h["_source"] for h in resp.get("hits", {}).get("hits", [])]
    except Exception:
        return []


def _pick_hit_index(chunks: list[dict], snippet: str) -> int | None:
    """在文档块里找与 snippet 最匹配的那一块，返回下标。

    用 `_norm_for_match`（与 /locate 同一套归一化）做双向包含 + 最长公共子串，
    这样 `【章节】` 前缀、全角/半角标点、LaTeX 残留都不会导致漏匹配。

    只在「有标题的正文块」里选：`heading_depth == 0` 的块是标题页/摘要页，
    不是引用要指的位置。全都不匹配时返回 `None` —— **宁可没有命中块，
    也不能给一个错的**。
    """
    target = _norm_for_match(snippet)
    if not target:
        return None

    from app.domain.retrieval.evidence import strip_chunk_prefix

    best_idx: int | None = None
    best_score = 0.0
    for i, c in enumerate(chunks):
        if not (c.get("heading_depth") or 0):
            continue
        body = _norm_for_match(strip_chunk_prefix(c.get("content")))
        if not body:
            continue

        contained = target in body
        sub_block = len(body) >= 4 and body in target
        overlap = _longest_common(target, body)

        if not contained and not sub_block and overlap < min(12, max(6, len(target) // 2)):
            continue

        score = (1000.0 if contained else 0.0) + overlap + min(len(body), 400) * 0.5
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


@router.get("/{doc_id}/evidence", response_model=EvidenceResponse)
async def get_document_evidence(
    doc_id: str,
    snippet: str = Query("", description="引用原文片段，用于定位命中章节与其上下文"),
    _user=Depends(get_current_user),
):
    """一篇文献的证据卡数据：摘要分段 + 样本量 + 连续上下文。

    组装逻辑全部委托 `app.domain.retrieval.evidence`（纯函数、可单测），
    本端点只负责三次取数：ES L0 元信息、doc-meta 摘要、ES L1 命中块与邻块。

    **失败不抛错**：任何一环取不到都返回部分数据 + `message` 说明，
    前端应展示已有的部分而不是整块报错 —— 证据卡是"锦上添花"，
    拿不到摘要也不该挡住用户看引用片段。
    """
    from app.domain.retrieval.evidence import (
        clean_display_text,
        extract_sample_size,
        has_conclusion,
        head_excerpt,
        prepare_hit_paragraphs,
        split_abstract_sections,
        strip_chunk_prefix,
        tail_excerpt,
    )

    l0 = _es_l0_source(doc_id)
    md5 = l0.get("md5")

    # doc-meta 的 md5 在 L0 里；L0 缺失时退回 /pdf/stream 那条查找链
    if not md5:
        object_path = await _find_pdf_object_name(doc_id)
        if object_path:
            md5 = object_path.split("/")[0]

    meta = _load_doc_meta_json(md5)

    abstract_raw = (meta.get("abstract_cn") or "").strip()
    if not abstract_raw:
        abstract_raw = _extract_abstract_from_l0(l0.get("content", ""))

    sections = split_abstract_sections(abstract_raw)
    conclusions = [s for s in sections if s.key in ("方法", "结果", "结论")]
    sample = extract_sample_size(*(s.text for s in conclusions))

    # 连续上下文：一次拉全部块，再在内存里定位命中处与前后邻居
    passage = None
    if snippet:
        chunks = _load_doc_l1_chunks(doc_id)
        idx = _pick_hit_index(chunks, snippet)
        if idx is not None:
            hit = chunks[idx]
            prev = chunks[idx - 1] if idx > 0 else None
            nxt = chunks[idx + 1] if idx + 1 < len(chunks) else None
            prev_paras = prepare_hit_paragraphs(prev.get("content")) if prev else []
            next_paras = prepare_hit_paragraphs(nxt.get("content")) if nxt else []
            passage = EvidencePassage(
                prev_heading=" → ".join(prev.get("heading_stack") or []) if prev else "",
                prev_text=tail_excerpt(" ".join(prev_paras)) if prev_paras else "",
                hit_heading=" → ".join(hit.get("heading_stack") or []),
                hit_paragraphs=prepare_hit_paragraphs(hit.get("content")),
                next_heading=" → ".join(nxt.get("heading_stack") or []) if nxt else "",
                next_text=head_excerpt(" ".join(next_paras)) if next_paras else "",
                has_prev=bool(prev_paras),
                has_next=bool(next_paras),
            )

    keywords = meta.get("keywords_cn") or l0.get("keywords_cn") or ""
    if isinstance(keywords, list):
        kw_list = [str(k) for k in keywords if str(k).strip()]
    else:
        kw_list = [k.strip() for k in re.split(r"[；;,，]", str(keywords)) if k.strip()]

    source = meta.get("source") or l0.get("source") or ""
    return EvidenceResponse(
        doc_id=doc_id,
        title=clean_display_text(meta.get("title_cn") or l0.get("title_cn") or ""),
        authors=meta.get("authors_cn") or l0.get("authors_cn") or "",
        journal=meta.get("journal") or l0.get("journal") or "",
        source=source,
        year=source.split(",")[0].strip(),
        article_type=(meta.get("article_type") or l0.get("article_type") or "").strip("• ").strip(),
        doi=meta.get("doi") or l0.get("doi") or "",
        keywords=kw_list,
        abstract_raw=clean_display_text(abstract_raw),
        abstract_sections=[
            AbstractSectionSchema(key=s.key, text=clean_display_text(s.text))
            for s in sections
        ],
        has_conclusion=has_conclusion(sections),
        sample_size=SampleSizeSchema(**sample.to_dict()) if sample else None,
        passage=passage,
        md5=md5,
        message="" if abstract_raw else "该文献无摘要记录",
    )
