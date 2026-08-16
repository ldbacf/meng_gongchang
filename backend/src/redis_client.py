"""Redis 队列 — 转发到 AppContainer（阶段 1：Redis Streams at-least-once）。

- `enqueue_batch` 签名改为 `token_id`（contract 4.2.1，禁存明文 MinerU token）。
- `dequeue_batch` 兼容返回 dict（worker 已改为经 `container.get_queue().claim()` 直接取）。
"""
from __future__ import annotations


async def get_redis():
    """经 AppContainer 获取共享 Redis 客户端。"""
    from app.interface.deps import get_container
    return get_container().get_redis()


async def enqueue_batch(batch_id: str, md5_list: list[str], token_id: str) -> None:
    """将 batch 推入 Streams 队列（payload 只含 token_id）。"""
    from app.interface.deps import get_container
    await get_container().get_queue().enqueue(batch_id, md5_list, token_id)


async def dequeue_batch(timeout: int = 5) -> dict | None:
    """兼容封装：经 Streams 队列 claim 一条批，返回 dict。"""
    from app.interface.deps import get_container
    job = await get_container().get_queue().claim(timeout=timeout)
    if job is None:
        return None
    m = job.message
    return {
        "batch_id": m.batch_id,
        "md5_list": m.md5_list,
        "token_id": m.token_id,
        "attempts": m.attempts,
        "_entry_id": job.entry_id,
    }
