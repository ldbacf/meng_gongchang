"""独立 worker 进程 — 消费可靠队列驱动 IngestionGraph（O-3.2）。

- claim → 写 `batch:{id}→token_id` 映射 → superseded 短路 → **batch 锁**（防同批双跑）
  → 图 ainvoke + interrupt resume 循环（poll pending 等待唤醒，C5）→ ack。
- 图是 pipeline_steps/status 唯一写入方；worker driver 不直接写库状态。
- 崩溃恢复：消息未 ack → XAUTOCLAIM 可见性超时回收（锁 TTL 300s 兜底在途批不被误回收）。
- Windows 需 SelectorEventLoop（psycopg async 不支持 ProactorEventLoop）。

入口：`python -m app.application.worker` 或 pyproject `pipeline-worker`。
"""
from __future__ import annotations

import asyncio
import sys
import time

from langgraph.types import Command

from app.application.checkpoint_registry import config_for, thread_id_for_batch

_POLL_WAKE = "wake"


async def _process_job(job) -> str:
    """处理一个队列批：驱动图直到完成（含 poll interrupt resume 循环）。"""
    from app.interface.deps import get_container

    container = get_container()
    queue = container.get_queue()
    graph = container.get_ingest_graph()
    settings = container.get_settings()
    redis = container.get_redis()

    m = job.message
    batch_id = m.batch_id

    # batch→token_id 映射（retry 兜底依赖）
    await redis.set(f"batch:{batch_id}", m.token_id, ex=7 * 24 * 3600)

    # superseded 短路：MinerU 重提交后旧批消息直接丢弃（防踩新 PENDING 状态）
    if await queue.is_superseded(batch_id):
        return "superseded"

    # 认领锁（claim 独占已保证，此锁兜底 retry/resume 路径）
    if not await queue.acquire_lock(batch_id):
        return "locked"

    cfg = config_for(thread_id_for_batch(batch_id))
    try:
        initial = {
            "batch_id": batch_id,
            "md5_list": m.md5_list,
            "token_id": m.token_id,
            "mode": m.mode,
            "poll_started_ts": time.time(),
            # 同 thread 重入（retry/resume）时清 checkpoint 残留的终态字段
            "fatal": False,
            "error": None,
        }
        await graph.ainvoke(initial, cfg)
        # interrupt resume 循环：poll pending → 等 POLL_INTERVAL → 唤醒继续
        while True:
            st = await graph.aget_state(cfg)
            if not st.interrupts:
                break
            await queue.renew_lock(batch_id)  # 长轮询批续租，防可见性超时误回收
            await asyncio.sleep(settings.poll_interval)
            await graph.ainvoke(Command(resume=_POLL_WAKE), cfg)
        return "done"
    finally:
        await queue.release_lock(batch_id)


async def run_worker():
    """消费循环（claim → 图 → ack）。"""
    from app.interface.deps import get_container

    container = get_container()
    await container.start()
    queue = container.get_queue()
    print("[Worker] 启动，等待任务...")

    try:
        while True:
            try:
                job = await queue.claim(timeout=5)
                if job is None:
                    continue
                await _process_job(job)
                await queue.ack(job.entry_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Worker] 异常: {e}")
                await asyncio.sleep(5)
    finally:
        await container.close()
    print("[Worker] 已停止")


def main() -> None:
    """独立进程入口（Windows 需 SelectorEventLoop 供 psycopg async）。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
