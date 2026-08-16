"""MinerU API 客户端 — 转发到 AppContainer 适配器（阶段 1）。

结构化异常 `MineruFatalError` / `MineruTransientError` 自
`app.infrastructure.adapters.mineru` 暴露，替代 worker 字符串匹配（阶段 3 正式落地分类）。
"""
from __future__ import annotations

from app.infrastructure.adapters.mineru import (  # noqa: F401  re-export
    MineruFatalError,
    MineruTransientError,
)


def _client():
    from app.interface.deps import get_container
    return get_container().get_mineru()


async def submit_batch(file_infos: list[dict], token: str) -> tuple[str, list[str]]:
    """使用指定 token 批量上传并提交解析。返回 (batch_id, md5_list)。"""
    return await _client().submit_batch(file_infos, token=token)


async def poll_batch(batch_id: str, token: str) -> list[dict]:
    """使用指定 token 轮询批量任务结果"""
    return await _client().poll_batch(batch_id, token=token)


async def download_result(download_url: str) -> bytes:
    return await _client().download_result(download_url)
