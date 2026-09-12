"""可靠队列端口抽象 — QueueAdapter（Redis Streams）实现之。"""
from __future__ import annotations

from typing import Protocol


class QueuePort(Protocol):
    """at-least-once 任务队列端口。"""

    async def enqueue(self, batch_id: str, md5_list: list[str], token_id: str) -> str: ...

    async def claim(self, timeout: float = 5.0) -> object | None: ...

    async def ack(self, entry_id: str) -> None: ...

    async def nack(self, entry_id: str) -> None: ...
