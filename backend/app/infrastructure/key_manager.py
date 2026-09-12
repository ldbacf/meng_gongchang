"""多 Key 额度管理与自动轮换 — Redis 持久化门面。

用法（三阶段语义，contract 4.2.2）:
    mgr = get_key_manager()
    res = await mgr.acquire(pdf_pages)      # best-fit 选 key + reserve 占额
    ... 提交 MinerU ...
    await mgr.commit([res])                  # 提交成功
    await mgr.refund([res])                  # 提交失败退回

- 额度账本在 Redis（`quota:{token_id}:{date}`），跨进程一致、重启保留（A-1.2）。
- `acquire` 返回 `Reservation(token_id, reservation_id, pages)`——明文 token 仅经
  TokenVault 在提交 MinerU 时解析，队列 payload 只存 token_id。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass


class TokenExhausted(Exception):
    """所有 token 当日额度均已用完"""


@dataclass
class Reservation:
    token_id: str
    reservation_id: str
    pages: int


class KeyManager:
    """额度管理器 — Redis 记账 + Best-fit 分配（选剩余最接近但不浪费的 key）。"""

    def __init__(self, vault, max_pages: int, quota_store):
        self._vault = vault
        self._max_pages = max_pages
        self._quota_store = quota_store

    async def remaining(self, token_id: str) -> int:
        return max(0, self._max_pages - await self._quota_store.balance(token_id))

    async def acquire(self, pages_needed: int) -> Reservation:
        """
        Best-fit 分配: 选剩余额度最接近 pages_needed 的 key（按 Redis balance），
        并 reserve 占额。返回 Reservation。
        """
        token_ids = self._vault.token_ids
        if not token_ids:
            raise RuntimeError("没有配置任何 API Token")

        best: str | None = None
        best_remain = 999999
        for tid in token_ids:
            rem = await self.remaining(tid)
            if rem >= pages_needed and rem < best_remain:
                best, best_remain = tid, rem

        if best is None:
            raise TokenExhausted(
                f"所有 Token 当日额度已用完 (max={self._max_pages}/key)\n"
                + await self.usage_report()
            )

        reservation_id = str(uuid.uuid4())
        await self._quota_store.reserve(best, pages_needed, reservation_id)
        return Reservation(token_id=best, reservation_id=reservation_id, pages=pages_needed)

    async def commit(self, reservations: list[Reservation]) -> None:
        """仅 MinerU 提交成功后调用：reserved → committed（额度已在预占时计入）。"""
        for r in reservations:
            await self._quota_store.commit(r.reservation_id)

    async def refund(self, reservations: list[Reservation]) -> None:
        """提交失败退回：reserved → refunded + DECR 当日计数。"""
        for r in reservations:
            await self._quota_store.refund(r.token_id, r.pages, r.reservation_id)

    async def usage_report(self) -> str:
        """格式化各 key 用量（token_id 显示）。"""
        lines = []
        for tid in self._vault.token_ids:
            used = await self._quota_store.balance(tid)
            remain = self._max_pages - used
            lines.append(f"  {tid}: {used}/{self._max_pages} (剩余{remain})")
        return "\n".join(lines)

    async def is_exhausted(self) -> bool:
        """所有 key 都满了吗"""
        return await self._quota_store.is_exhausted(
            self._vault.token_ids, self._max_pages
        )


def get_key_manager():
    """经 AppContainer 获取 KeyManager（容器单例）。"""
    from app.interface.deps import get_container
    return get_container().get_key_manager()
