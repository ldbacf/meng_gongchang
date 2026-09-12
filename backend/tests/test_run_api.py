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
    """main() 不得传 workers/reload（子进程会强制回 Proactor，checkpointer 再次失效）。"""
    captured = {}
    monkeypatch.setattr(run_api, "_configure_event_loop", lambda: None)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update({"app": app, **kw}))
    monkeypatch.setattr(sys, "argv", ["medrag-api", "--port", "8123"])

    run_api.main()

    assert captured["app"] == "app.main:app"
    assert captured["port"] == 8123
    assert "workers" not in captured and "reload" not in captured
