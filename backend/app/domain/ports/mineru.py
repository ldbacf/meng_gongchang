"""MinerU 解析端口抽象 — MineruClient 实现之。"""
from __future__ import annotations

from typing import Protocol


class MineruPort(Protocol):
    """MinerU 批量提交 / 轮询 / 下载端口。"""

    async def submit_batch(
        self, file_infos: list[dict], token: str
    ) -> tuple[str, list[str]]: ...

    async def poll_batch(self, batch_id: str, token: str) -> list[dict]: ...

    async def download_result(self, download_url: str) -> bytes: ...
