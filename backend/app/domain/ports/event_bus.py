"""事件总线端口抽象 — 阶段 1 EventBusRedis 实现之。"""
from __future__ import annotations

from typing import Protocol


class EventBusPort(Protocol):
    """按 topic 发布/订阅的事件总线端口。"""

    async def publish(self, topic: str, event: dict) -> None: ...

    async def subscribe(self, topic: str): ...
