"""额度记账端口抽象 — QuotaStoreRedis 实现之。"""
from __future__ import annotations

from typing import Protocol


class QuotaPort(Protocol):
    """额度三阶段记账端口（reserve → commit / refund）。"""

    async def reserve(self, key_id: str, pages: int, reservation_id: str) -> int: ...

    async def commit(self, reservation_id: str) -> bool: ...

    async def refund(self, key_id: str, pages: int, reservation_id: str) -> bool: ...

    async def balance(self, key_id: str) -> int: ...
