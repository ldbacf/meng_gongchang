"""WebSocket 连接管理器 — 按 kb_id 分组广播文档状态变更"""

from collections import defaultdict
import logging

from fastapi import WebSocket

logger = logging.getLogger("ws_manager")


class WSManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, kb_id: str):
        await ws.accept()
        self._connections[kb_id].add(ws)
        logger.info("WS connect kb=%s (total=%d)", kb_id, len(self._connections[kb_id]))

    def disconnect(self, ws: WebSocket, kb_id: str):
        self._connections[kb_id].discard(ws)
        if not self._connections[kb_id]:
            del self._connections[kb_id]
        logger.info("WS disconnect kb=%s", kb_id)

    async def broadcast(self, kb_id: str, event: dict):
        if not kb_id:
            return
        kb_id = str(kb_id)
        conns = self._connections.get(kb_id, set())
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
            if not conns and kb_id in self._connections:
                del self._connections[kb_id]


ws_manager = WSManager()


async def broadcast_doc_update(task, kb_id=None):
    """序列化 DocumentTask → broadcast doc_update 事件。kb_id=None 时自动从 task 读取。"""
    kid = kb_id or getattr(task, "kb_id", None)
    if not kid:
        return
    from src.schemas import DocumentResponse

    try:
        doc_data = DocumentResponse.model_validate(task).model_dump(mode="json")
    except Exception:
        return
    await ws_manager.broadcast(str(kid), {"type": "doc_update", "doc": doc_data})
