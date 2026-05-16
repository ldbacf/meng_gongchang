"""Redis 队列 — 用于存放待轮询的 batch_id"""

import json

import redis.asyncio as aioredis

from src.config import REDIS_URL, REDIS_QUEUE

_pool: aioredis.ConnectionPool | None = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    return aioredis.Redis(connection_pool=_pool)


async def enqueue_batch(batch_id: str, md5_list: list[str], token: str) -> None:
    """将 batch_id + token 推入轮询队列"""
    r = await get_redis()
    payload = json.dumps({
        "batch_id": batch_id,
        "md5_list": md5_list,
        "token": token,
    })
    await r.lpush(REDIS_QUEUE, payload)


async def dequeue_batch(timeout: int = 5) -> dict | None:
    """阻塞式从队列取出一个 batch_id"""
    r = await get_redis()
    raw = await r.brpop(REDIS_QUEUE, timeout=timeout)
    if raw is None:
        return None
    return json.loads(raw[1])
