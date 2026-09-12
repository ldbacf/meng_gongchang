"""T-1.9 — 事件总线 roundtrip：publish → subscribe → ws fanout 收到 doc_update/doc_deleted。

fakeredis 2.37 的 aioredis PubSub 不广播（已验证），故用内存双端 fake 总线验证
WSRegistry 的订阅→fanout 语义；EventBusRedis 的 publish 命令在 fakeredis 上不抛错。
真实 Redis 集成见阶段报告（docker 环境手动验证 A-1.6）。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.infrastructure.ws_manager import WSRegistry


class _FakePubSub:
    def __init__(self, queue: asyncio.Queue):
        self._q = queue

    async def get_message(self, ignore_subscribe_messages=False, timeout=None):
        try:
            return await asyncio.wait_for(self._q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def aclose(self):
        pass


class InMemoryEventBus:
    """publish → 投递到订阅者的队列（模拟 Redis Pub/Sub 的订阅-广播语义）。"""

    def __init__(self):
        self._topics: dict[str, asyncio.Queue] = {}

    async def subscribe(self, topic: str) -> _FakePubSub:
        q: asyncio.Queue = asyncio.Queue()
        self._topics[topic] = q
        return _FakePubSub(q)

    async def publish(self, topic: str, event: dict) -> None:
        q = self._topics.get(topic)
        if q is not None:
            await q.put({"type": "message", "data": json.dumps(event)})


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def send_json(self, event: dict):
        self.sent.append(event)


@pytest.mark.asyncio
async def test_event_bus_roundtrip_doc_update():
    """publish doc_update → WS 订阅者收到。"""
    bus = InMemoryEventBus()
    reg = WSRegistry(bus)
    ws = _FakeWS()

    await reg.connect(ws, "kb-1")
    await asyncio.sleep(0.05)  # 等订阅任务建立（create_task 异步调度）
    await bus.publish("kb-1", {"type": "doc_update", "doc": {"md5": "abc"}})
    await asyncio.sleep(0.05)  # 等订阅任务 fanout

    assert any(e.get("type") == "doc_update" for e in ws.sent)
    assert any(e.get("doc", {}).get("md5") == "abc" for e in ws.sent)

    reg.disconnect(ws, "kb-1")


@pytest.mark.asyncio
async def test_event_bus_roundtrip_doc_deleted():
    """publish doc_deleted → WS 订阅者收到。"""
    bus = InMemoryEventBus()
    reg = WSRegistry(bus)
    ws = _FakeWS()

    await reg.connect(ws, "kb-1")
    await asyncio.sleep(0.05)  # 等订阅任务建立
    await bus.publish("kb-1", {"type": "doc_deleted", "doc_id": "d-1"})
    await asyncio.sleep(0.05)

    assert any(e.get("type") == "doc_deleted" and e.get("doc_id") == "d-1" for e in ws.sent)
    reg.disconnect(ws, "kb-1")


@pytest.mark.asyncio
async def test_broadcast_publishes_to_bus():
    """WSRegistry.broadcast 发布到事件总线（跨进程语义）。"""
    bus = InMemoryEventBus()
    reg = WSRegistry(bus)
    ws = _FakeWS()
    await reg.connect(ws, "kb-2")
    await asyncio.sleep(0.05)  # 等订阅任务建立

    await reg.broadcast("kb-2", {"type": "doc_update", "doc": {}})
    await asyncio.sleep(0.05)

    assert ws.sent  # 发布 → 订阅回环 → fanout 到本地连接
    reg.disconnect(ws, "kb-2")


@pytest.mark.asyncio
async def test_event_bus_redis_publish_no_error(fake_redis):
    """EventBusRedis.publish 在 fakeredis 上执行不抛错（命令层验证）。"""
    from app.infrastructure.redis.event_bus_redis import EventBusRedis

    bus = EventBusRedis.__new__(EventBusRedis)  # 不建真实连接
    bus._redis = fake_redis
    await bus.publish("kb-1", {"type": "doc_update", "doc": {}})
