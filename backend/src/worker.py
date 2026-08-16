"""后台 Worker — 多 Token 支持（阶段 1：Redis Streams at-least-once）。

- 经 `container.get_queue().claim()` 取批（XREADGROUP + XAUTOCLAIM 回收崩溃 pending），
  处理完成 `ack`；进程被杀 → 不 ack → 可见性超时后另一 worker 恢复（A-1.3）。
- 队列 payload 只含 token_id；明文 token 经 TokenVault 解析。
- MinerU 错误用结构化异常（MineruFatalError/MineruTransientError），字符串匹配兜底。
"""

import asyncio
import signal
import time

from sqlalchemy import select

from app.domain.knowledge_base import KBKind, resolve_kb_kind
from app.interface.deps import get_container
from src.config import MAX_POLL_TIME, POLL_INTERVAL
from src.db import async_session
from src.mineru_client import (
    MineruFatalError,
    MineruTransientError,
    download_result,
    poll_batch,
)
from src.minio_client import upload_parsed_assets
from src.models import DocumentTask, TaskStatus
from src.ws_manager import broadcast_doc_update

STATE_LABELS = {
    "waiting-file": "等待上传",
    "pending":      "排队中",
    "running":      "解析中",
    "converting":   "格式转换中",
    "done":         "已完成",
    "failed":       "失败",
}


def _step_update(task, step: str, status: str, **kwargs):
    """在 task.pipeline_steps 里更新指定步骤状态（ts 统一 float，阶段 2 双轨合一）"""
    if task.pipeline_steps is None:
        return
    import time as _time
    task.pipeline_steps[step] = {"status": status, "ts": _time.time(), **kwargs}


async def _process_one_batch(batch_id: str, md5_list: list[str], token_id: str):
    """使用指定 token_id 轮询（明文 token 经 vault 解析）。"""
    token = get_container().get_token_vault().resolve(token_id) or ""
    print(f"[Worker] 轮询 batch_id={batch_id} token_id={token_id}")
    start = time.time()
    pending = set(md5_list)

    while pending and (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start

        try:
            items = await poll_batch(batch_id, token=token)
        except MineruFatalError as e:
            print(f"[Worker] batch 不可恢复, 直接标记失败: {e}")
            for md5 in pending:
                async with async_session() as session:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                    r = await session.execute(stmt)
                    t = r.scalar_one_or_none()
                    if t:
                        t.set_status(TaskStatus.FAILED)
                        t.error_msg = str(e)
                        _step_update(t, "mineru", "failed", error=str(e))
                        await session.commit()
                        await broadcast_doc_update(t)
            return
        except MineruTransientError as e:
            print(f"[Worker] 查询失败 ({elapsed:.0f}s): {e}，稍后重试")
            continue
        except Exception as e:
            err_msg = str(e)
            print(f"[Worker] 查询失败 ({elapsed:.0f}s): {err_msg}")

            # 兜底字符串匹配（结构化分类迁移在阶段 3 正式落地）
            if any(kw in err_msg for kw in ("找不到任务", "没有权限", "Token 错误", "Token 过期")):
                print(f"[Worker] batch 不可恢复, 直接标记失败")
                for md5 in pending:
                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        r = await session.execute(stmt)
                        t = r.scalar_one_or_none()
                        if t:
                            t.set_status(TaskStatus.FAILED)
                            t.error_msg = err_msg
                            _step_update(t, "mineru", "failed", error=err_msg)
                            await session.commit()
                            await broadcast_doc_update(t)
                return
            continue

        for item in items:
            md5 = item.get("data_id") or item.get("file_name")
            if md5 not in pending:
                continue

            state = item["state"]
            label = STATE_LABELS.get(state, state)
            fname = item.get("file_name", md5)
            print(f"[Worker] {fname}: {label} ({elapsed:.0f}s)")

            if state == "done":
                try:
                    zip_bytes = await download_result(item["full_zip_url"])
                    md_url = upload_parsed_assets(md5, zip_bytes)
                    print(f"[Worker] {fname}: 已存入 MinIO -> {md_url}")

                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        result = await session.execute(stmt)
                        task = result.scalar_one_or_none()
                        if task:
                            # 状态机推进：重跑场景 PENDING→PROCESSING→PARSED；正常 PROCESSING→PARSED
                            if task.status == TaskStatus.PENDING.value:
                                task.set_status(TaskStatus.PROCESSING)
                            task.set_status(TaskStatus.PARSED)
                            task.parsed_minio_path = md_url
                            _step_update(task, "mineru", "done")
                            await session.commit()
                            await broadcast_doc_update(task)

                            # 通用 KB → 触发索引
                            if task.kb_id:
                                from src.models import KnowledgeBase
                                kb_result = await session.execute(
                                    select(KnowledgeBase).where(
                                        KnowledgeBase.id == task.kb_id,
                                    )
                                )
                                kb = kb_result.scalar_one_or_none()
                                if kb and resolve_kb_kind(kb) is not KBKind.MEDICAL_DEFAULT:
                                    # 用局部 dict 记录索引步骤状态，避免子线程摸 ORM 对象
                                    import copy as _copy
                                    import time as _time
                                    steps_ref = _copy.deepcopy(task.pipeline_steps) if task.pipeline_steps else {}
                                    def _local_step_update(step, status, **kw):
                                        if steps_ref is not None:
                                            steps_ref[step] = {"status": status, "ts": _time.time(), **kw}

                                    try:
                                        task.set_status(TaskStatus.INDEXING)
                                        await session.commit()
                                        await broadcast_doc_update(task)

                                        from src.indexer import process_document
                                        n = await asyncio.to_thread(
                                            process_document,
                                            md5, task.original_name,
                                            kb.es_index, kb.milvus_collection,
                                            on_step=_local_step_update,
                                        )
                                        # 将线程修改后的步骤状态写回 ORM 对象
                                        if steps_ref is not None:
                                            task.pipeline_steps = dict(steps_ref)
                                        task.set_status(TaskStatus.READY)
                                        print(f"[Worker] {fname}: 索引完成 ({n} chunks)")
                                    except Exception as e:
                                        task.set_status(TaskStatus.FAILED)
                                        task.error_msg = f"索引失败: {e}"
                                        if steps_ref is not None:
                                            # 修复：把实际 running 步骤置 failed（原写 steps_ref["failed"] 垃圾 key）
                                            for _sn, _st in steps_ref.items():
                                                if isinstance(_st, dict) and _st.get("status") == "running":
                                                    _st["status"] = "failed"
                                                    _st["error"] = str(e)
                                            task.pipeline_steps = dict(steps_ref)
                                        print(f"[Worker] {fname}: 索引失败: {e}")
                                    await session.commit()
                                    await broadcast_doc_update(task)
                except Exception as e:
                    print(f"[Worker] {fname}: 下载/解包失败: {e}")
                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        result = await session.execute(stmt)
                        task = result.scalar_one_or_none()
                        if task:
                            task.set_status(TaskStatus.FAILED)
                            task.error_msg = str(e)
                            await session.commit()
                            await broadcast_doc_update(task)
                pending.discard(md5)

            elif state == "failed":
                err = item.get("err_msg", "未知错误")
                print(f"[Worker] {fname}: 解析失败: {err}")
                async with async_session() as session:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                    result = await session.execute(stmt)
                    task = result.scalar_one_or_none()
                    if task:
                        task.set_status(TaskStatus.FAILED)
                        task.error_msg = err
                        await session.commit()
                        await broadcast_doc_update(task)
                pending.discard(md5)

    for md5 in pending:
        print(f"[Worker] {md5}: 超时")
        async with async_session() as session:
            stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                task.set_status(TaskStatus.FAILED)
                task.error_msg = "轮询超时"
                await session.commit()
                await broadcast_doc_update(task)


async def _run_loop(stop_event: asyncio.Event | None):
    """消费循环：claim → 处理 → ack。进程崩溃则消息不 ack，可见性超时后恢复。"""
    container = get_container()
    queue = container.get_queue()
    redis = container.get_redis()
    print("[Worker] 启动，等待任务...")

    while stop_event is None or not stop_event.is_set():
        try:
            job = await queue.claim(timeout=5)
            if job is None:
                continue
            m = job.message
            # batch_id → token_id 映射（重试用；worker 崩溃后 Streams pending 无 token 上下文）
            await redis.set(f"batch:{m.batch_id}", m.token_id, ex=7 * 24 * 3600)
            await _process_one_batch(m.batch_id, m.md5_list, m.token_id)
            await queue.ack(job.entry_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Worker] 异常: {e}")
            await asyncio.sleep(5)
    print("[Worker] 已停止")


async def run_worker():
    """独立 worker 进程入口（pyproject `pipeline-worker`）。"""
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        stop = True
        print("[Worker] 收到退出信号")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop:
        try:
            job = await get_container().get_queue().claim(timeout=5)
            if job is None:
                continue
            m = job.message
            await get_container().get_redis().set(
                f"batch:{m.batch_id}", m.token_id, ex=7 * 24 * 3600
            )
            await _process_one_batch(m.batch_id, m.md5_list, m.token_id)
            await get_container().get_queue().ack(job.entry_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Worker] 异常: {e}")
            await asyncio.sleep(5)


async def run_worker_background(stop_event: asyncio.Event):
    """后台 Worker — 由 FastAPI lifespan 管理，不需要 signal。"""
    await _run_loop(stop_event)


if __name__ == "__main__":
    asyncio.run(run_worker())
