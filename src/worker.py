"""后台 Worker — 多 Token 支持"""

import asyncio
import signal
import time

from sqlalchemy import select

from src.config import MAX_POLL_TIME, POLL_INTERVAL
from src.db import async_session
from src.mineru_client import download_result, poll_batch
from src.minio_client import upload_parsed_assets
from src.models import DocumentTask, TaskStatus
from src.redis_client import dequeue_batch
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
    """在 task.pipeline_steps 里更新指定步骤状态"""
    if task.pipeline_steps is None:
        return
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    task.pipeline_steps[step] = {"status": status, "ts": now, **kwargs}


async def _process_one_batch(batch_id: str, md5_list: list[str], token: str):
    """使用指定 token 轮询"""
    print(f"[Worker] 轮询 batch_id={batch_id} token={token[:8]}...")
    start = time.time()
    pending = set(md5_list)

    while pending and (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start

        try:
            items = await poll_batch(batch_id, token=token)
        except Exception as e:
            err_msg = str(e)
            print(f"[Worker] 查询失败 ({elapsed:.0f}s): {err_msg}")

            # 致命错误: batch 不存在 / token 失效 → 直接标记失败
            if any(kw in err_msg for kw in ("找不到任务", "没有权限", "Token 错误", "Token 过期")):
                print(f"[Worker] batch 不可恢复, 直接标记失败")
                for md5 in pending:
                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        r = await session.execute(stmt)
                        t = r.scalar_one_or_none()
                        if t:
                            t.status = TaskStatus.FAILED
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
                            task.status = TaskStatus.PARSED
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
                                if kb and kb.slug != "zhong_guo_quan_ke":
                                    # 用局部 dict 记录索引步骤状态，避免子线程摸 ORM 对象
                                    import datetime as _dt
                                    import copy as _copy
                                    steps_ref = _copy.deepcopy(task.pipeline_steps) if task.pipeline_steps else {}
                                    def _local_step_update(step, status, **kw):
                                        if steps_ref is not None:
                                            steps_ref[step] = {"status": status, "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), **kw}

                                    try:
                                        task.status = TaskStatus.INDEXING
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
                                        task.status = TaskStatus.READY
                                        print(f"[Worker] {fname}: 索引完成 ({n} chunks)")
                                    except Exception as e:
                                        task.status = TaskStatus.FAILED
                                        task.error_msg = f"索引失败: {e}"
                                        if steps_ref is not None:
                                            steps_ref[task.status.lower()] = {"status": "failed", "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), "error": str(e)}
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
                            task.status = TaskStatus.FAILED
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
                        task.status = TaskStatus.FAILED
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
                task.status = TaskStatus.FAILED
                task.error_msg = "轮询超时"
                await session.commit()
                await broadcast_doc_update(task)


async def run_worker():
    print("[Worker] 启动，等待任务...")
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        stop = True
        print("[Worker] 收到退出信号")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop:
        try:
            job = await dequeue_batch(timeout=5)
            if job is None:
                continue
            await _process_one_batch(
                job["batch_id"],
                job["md5_list"],
                job.get("token", ""),
            )
        except Exception as e:
            print(f"[Worker] 异常: {e}")
            await asyncio.sleep(5)


async def run_worker_background(stop_event: asyncio.Event):
    """后台 Worker — 由 FastAPI lifespan 管理，不需要 signal"""
    print("[Worker] 后台启动，等待任务...")
    while not stop_event.is_set():
        try:
            job = await asyncio.wait_for(dequeue_batch(timeout=5), timeout=10)
            if job is None:
                continue
            await _process_one_batch(
                job["batch_id"],
                job["md5_list"],
                job.get("token", ""),
            )
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print(f"[Worker] 异常: {e}")
            await asyncio.sleep(5)
    print("[Worker] 已停止")

    print("[Worker] 已退出")


if __name__ == "__main__":
    asyncio.run(run_worker())
