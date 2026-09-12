"""WebSocket 连接管理器 — 进程内注册表 + Redis 事件总线（阶段 1）。

- `WSRegistry.broadcast()`：保留原签名，内部改为**发布到事件总线**（topic=kb_id），
  跨进程可收（A-1.6）；本地订阅任务收件后 fanout 到本进程连接。
- 订阅模型：**每进程每 kb 一个 pubsub 订阅任务 + 引用计数**（首个连接 subscribe、
  归零 unsubscribe），避免 N 连接 N 订阅双发。
- worker / admin / main 全部经 `broadcast_doc_update` 发事件。
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("ws_manager")


class WSRegistry:
    """进程内 WS 连接注册表 + 每 kb 一个 pubsub 订阅任务（引用计数）。"""

    def __init__(self, event_bus):
        self._event_bus = event_bus
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._subs: dict[str, asyncio.Task] = {}
        self._refcount: dict[str, int] = defaultdict(int)

    async def connect(self, ws: WebSocket, kb_id: str):
        await ws.accept()
        kid = str(kb_id)
        self._connections[kid].add(ws)
        self._refcount[kid] += 1
        if kid not in self._subs:
            self._subs[kid] = asyncio.create_task(self._subscribe_loop(kid))
        logger.info("WS connect kb=%s (total=%d)", kid, len(self._connections[kid]))

    def disconnect(self, ws: WebSocket, kb_id: str):
        kid = str(kb_id)
        self._connections[kid].discard(ws)
        self._refcount[kid] -= 1
        if not self._connections[kid]:
            self._connections.pop(kid, None)
            self._refcount.pop(kid, None)
            task = self._subs.pop(kid, None)
            if task:
                task.cancel()
        logger.info("WS disconnect kb=%s", kid)

    async def broadcast(self, kb_id, event: dict):
        """保留原签名：发布到事件总线（跨进程可收），由订阅回环 fanout 到本地连接。"""
        if not kb_id:
            return
        await self._event_bus.publish(str(kb_id), event)

    async def _subscribe_loop(self, kid: str):
        try:
            ps = await self._event_bus.subscribe(kid)
        except Exception:
            logger.exception("WS 订阅失败 kb=%s", kid)
            return
        try:
            while True:
                msg = await ps.get_message(
                    ignore_subscribe_messages=True, timeout=10.0
                )
                if msg is None or msg.get("type") != "message":
                    continue
                try:
                    event = json.loads(msg["data"])
                except Exception:
                    continue
                await self._fanout(kid, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WS 订阅循环异常 kb=%s", kid)
        finally:
            try:
                await ps.aclose()
            except Exception:
                pass

    async def _fanout(self, kid: str, event: dict):
        conns = self._connections.get(kid, set())
        if not conns:
            return
        dead: set[WebSocket] = set()
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:
                dead.add(ws)
        if dead:
            conns -= dead
            if not conns:
                self._connections.pop(kid, None)


def get_ws_registry():
    """经 AppContainer 获取 WSRegistry（容器单例）。"""
    from app.interface.deps import get_container
    return get_container().get_ws_registry()


async def broadcast_doc_update(task, kb_id=None):
    """序列化 DocumentTask → 发布 doc_update 事件（经事件总线，跨进程可收）。"""
    kid = kb_id or getattr(task, "kb_id", None)
    if not kid:
        return
    from app.interface.schemas import DocumentResponse

    try:
        doc_data = DocumentResponse.model_validate(task).model_dump(mode="json")
    except Exception:
        return
    await get_ws_registry().broadcast(str(kid), {"type": "doc_update", "doc": doc_data})
