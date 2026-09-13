"""T-5.12 — API 启动入口：Windows 下设 SelectorEventLoop（psycopg async 要求）。

不真起 uvicorn：只验证 `_configure_event_loop` 的平台分支（monkeypatch 掉
`set_event_loop_policy`，避免污染同进程其他测试的全局策略）。
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from app import run_api


def test_win32_sets_selector_policy(monkeypatch):
    if not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        pytest.skip("非 Windows，无 SelectorEventLoopPolicy")
    calls = []
    monkeypatch.setattr(run_api.asyncio, "set_event_loop_policy", lambda p: calls.append(p))
    monkeypatch.setattr(run_api.sys, "platform", "win32")

    run_api._configure_event_loop()

    assert len(calls) == 1
    assert isinstance(calls[0], asyncio.WindowsSelectorEventLoopPolicy)


def test_non_win32_leaves_policy_untouched(monkeypatch):
    calls = []
    monkeypatch.setattr(run_api.asyncio, "set_event_loop_policy", lambda p: calls.append(p))
    monkeypatch.setattr(run_api.sys, "platform", "linux")

    run_api._configure_event_loop()

    assert calls == []


def test_main_does_not_pass_workers(monkeypatch):
    """main() 不得传 workers/reload（子进程路径行为不同）。"""
    captured = {}
    monkeypatch.setattr(run_api, "_configure_event_loop", lambda: None)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update({"app": app, **kw}))
    monkeypatch.setattr(sys, "argv", ["medrag-api", "--port", "8123"])

    run_api.main()

    assert captured["app"] == "app.main:app"
    assert captured["port"] == 8123
    assert "workers" not in captured and "reload" not in captured


def test_main_passes_loop_none(monkeypatch):
    """必须传 loop="none"。

    uvicorn ≥0.36 在 Server.run 里把 loop_factory 显式传给 asyncio.run，而传了
    loop_factory 就会**绕过 event loop policy**；且 uvicorn 在 Windows 上把该 factory
    硬编码为 ProactorEventLoop（见 uvicorn/loops/asyncio.py）。只有 loop="none"
    （→ loop_factory=None）才会回落到我们设的 SelectorEventLoopPolicy，
    psycopg async 才能用，checkpointer 才建得出来。
    """
    captured = {}
    monkeypatch.setattr(run_api, "_configure_event_loop", lambda: None)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update({"app": app, **kw}))
    monkeypatch.setattr(sys, "argv", ["medrag-api"])

    run_api.main()

    assert captured.get("loop") == "none", (
        "uvicorn 默认 loop=auto 在 Windows 返回 ProactorEventLoop，会绕过 policy"
    )
