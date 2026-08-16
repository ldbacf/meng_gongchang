"""T-1.11 — MinerU 客户端结构化异常：429 重试耗尽 → Transient；致命文案 → Fatal。"""
from __future__ import annotations

import httpx
import pytest

from app.infrastructure.adapters.mineru import (
    MineruClient,
    MineruFatalError,
    MineruTransientError,
)


class _FakeResp429:
    status_code = 429

    def raise_for_status(self):
        raise httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=httpx.Request("POST", "http://mineru"),
            response=self,
        )

    def json(self):
        return {}


class _FakeRespFatal:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"code": 1, "msg": "找不到任务"}


class _FakeHTTP:
    """mock httpx.AsyncClient：post/get 返回固定响应。"""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._resp

    async def get(self, *a, **k):
        return self._resp


@pytest.mark.asyncio
async def test_429_retries_then_transient(monkeypatch):
    """429 重试耗尽仍失败 → MineruTransientError（可重试）。"""
    async def _noop(*a, **k):
        pass

    monkeypatch.setattr("app.infrastructure.adapters.mineru.asyncio.sleep", _noop)
    client = MineruClient()
    monkeypatch.setattr(client, "_api_client", lambda: _FakeHTTP(_FakeResp429()))

    with pytest.raises(MineruTransientError):
        await client._post("/api/v4/file-urls/batch", {}, "tk_1")


@pytest.mark.asyncio
async def test_fatal_keyword_raises_fatal(monkeypatch):
    """致命文案（找不到任务）→ MineruFatalError（不可重试）。"""
    client = MineruClient()
    monkeypatch.setattr(client, "_api_client", lambda: _FakeHTTP(_FakeRespFatal()))

    with pytest.raises(MineruFatalError):
        await client._get("/api/v4/extract-results/batch/x", "tk_1")


@pytest.mark.asyncio
async def test_network_error_raises_transient(monkeypatch):
    """网络错误 → MineruTransientError。"""

    class _NetErrHTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("connection refused")

    client = MineruClient()
    monkeypatch.setattr(client, "_api_client", lambda: _NetErrHTTP())

    with pytest.raises(MineruTransientError):
        await client._get("/x", "tk_1")
