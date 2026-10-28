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
    from app.infrastructure.container import get_container

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
    """消费循环（claim → 图 → ack）。

    ## 失败必须显式 nack，不能只 log 后继续

    原先这里是 `except Exception: log; sleep(5); continue` —— 消息留在
    pending 里既没 ack 也没 nack，只能等 `queue_visibility_timeout`
    （默认 1800s）到期才被 XAUTOCLAIM 回收重投。于是一次可重试的失败
    （例如 `indexing → indexing` 非法迁移）会让这个批**固定卡 30 分钟**，
    而且全程没有任何失败信号：界面上就是「索引中」一直不动。

    现在按端口语义处理：
      - `TransientError` → `nack()`：attempts+1 立即重投，超限进 DLQ。
      - 其他异常（Fatal / 编程错误）→ 也走 `nack()`，让重试计数生效，
        最终进 DLQ 而不是静默悬挂 —— 悬挂比失败更难排查。
    """
    from app.infrastructure.container import get_container
    from app.infrastructure.observability.logger import get_logger, setup_logging

    # 与 API 共用同一套 JSON 日志（原先用 print，格式和级别都与另两个进程不一致）
    setup_logging()
    log = get_logger("app.worker")

    container = get_container()
    log.info("worker 启动，等待任务…")
    await container.start()
    queue = container.get_queue()

    try:
        while True:
            try:
                job = await queue.claim(timeout=5)
                if job is None:
                    continue
                log.info("收到任务", extra={"ctx": {"entry_id": job.entry_id}})
                try:
                    outcome = await _process_job(job)
                except Exception as e:
                    # 显式 nack：立即重投（attempts+1），超限进 DLQ。
                    # 不 nack 就要等 1800s 可见性超时，期间界面无任何反馈。
                    log.error(
                        "任务处理失败，nack 重投: %s",
                        e,
                        exc_info=True,
                        extra={"ctx": {"entry_id": job.entry_id}},
                    )
                    await queue.nack(job.entry_id)
                    await asyncio.sleep(2)  # 轻微退避，避免瞬间打满重试计数
                    continue
                await queue.ack(job.entry_id)
                log.info(
                    "任务完成并 ack",
                    extra={"ctx": {"entry_id": job.entry_id, "outcome": outcome}},
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("消费异常，5s 后重试: %s", e, exc_info=True)
                await asyncio.sleep(5)
    finally:
        await container.close()
    log.info("worker 已停止")


def _run_once() -> None:
    """跑一遍消费循环（Windows 需 SelectorEventLoop 供 psycopg async）。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_worker())


def main() -> None:
    """独立进程入口。

    `--reload` 用 watchfiles 监视 `backend/app`，改动后**重启整个进程**
    （不是热替换模块）—— 消费循环里持有队列连接与图状态，就地重载会留下半截状态。

    ```bash
    uv run pipeline-worker --reload
    ```
    """
    import argparse

    ap = argparse.ArgumentParser(description="MedRAG 文档处理 worker")
    ap.add_argument("--reload", action="store_true", help="改代码自动重启（仅本地开发）")
    args = ap.parse_args()

    if not args.reload:
        _run_once()
        return

    from watchfiles import run_process

    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent  # backend/app
    print(f"[worker] reload 已开启，监视 {app_dir}")
    run_process(app_dir, target=_run_once, target_type="function")


if __name__ == "__main__":
    main()
