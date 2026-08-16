"""事件总线适配器 — Redis Pub/Sub，按 topic（kb_id）跨进程广播。

- worker / admin / API 进程 publish；ws 层 subscribe 后 fanout 到前端（A-1.6 跨进程可收）。
- **pubsub 用专用连接**（从共享池创建会长期独占池连接，耗尽池）。
- 事件类型见 contract 4.2.3：doc_update / doc_deleted / step。
- 断线重连/快照 resync 留阶段 4（SSE 升级）处理；本阶段保证 at-most-once 语义。
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis


class EventBusRedis:
    def __init__(self, redis_url: str):
        # 独立客户端（与共享池分离），pubsub 从该客户端拿专用连接
        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
        )

    async def publish(self, topic: str, event: dict) -> None:
        """向 topic（kb_id）发布一条事件。"""
        await self._redis.publish(topic, json.dumps(event, ensure_ascii=False))

    async def subscribe(self, topic: str):
        """订阅 topic，返回 aioredis PubSub 对象（调用方负责 get_message 循环与 close）。"""
        ps = self._redis.pubsub()
        await ps.subscribe(topic)
        return ps

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:
            pass
