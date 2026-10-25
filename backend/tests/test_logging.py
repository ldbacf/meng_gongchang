"""日志与访问中间件的回归测试。

锁住三件事：
1. `setup_logging` 输出的每行都是 JSON（level/ts/msg/logger，可选 ctx/exc）
2. `LOG_LEVEL` 经 Settings 生效；uvicorn 自带访问日志被压掉（避免与中间件重复）
3. `RequestLogMiddleware` 对普通请求记 INFO，对探针路径（/health 等）只记 DEBUG
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.observability import logger as obs
from app.interface.middleware import RequestLogMiddleware


# ── 格式化 ─────────────────────────────────────────────────


def test_json_formatter_shape():
    fmt = obs.JsonFormatter()
    record = logging.LogRecord(
        name="app.demo", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    record.ctx = {"k": 1}
    payload = json.loads(fmt.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.demo"
    assert payload["msg"] == "hello world"
    assert payload["ctx"] == {"k": 1}
    assert "ts" in payload


def test_json_formatter_includes_traceback():
    fmt = obs.JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="app.demo", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="failed", args=(), exc_info=exc_info,
    )
    payload = json.loads(fmt.format(record))
    assert "ValueError: boom" in payload["exc"]


# ── setup_logging ──────────────────────────────────────────


def test_setup_logging_installs_single_json_handler():
    obs.setup_logging(logging.DEBUG)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, obs.JsonFormatter)


def test_uvicorn_access_muted_but_error_kept():
    obs.setup_logging(logging.INFO)
    assert logging.getLogger("uvicorn.access").level >= logging.WARNING
    # 启动信息（"Uvicorn running on ..."）走 uvicorn.error，应保留 INFO
    assert logging.getLogger("uvicorn.error").level == logging.INFO


def test_noisy_libs_are_warning():
    obs.setup_logging(logging.DEBUG)
    for name in ("httpx", "httpcore", "urllib3"):
        assert logging.getLogger(name).level >= logging.WARNING


@pytest.mark.parametrize("raw,expected", [
    ("debug", logging.DEBUG),
    ("INFO", logging.INFO),
    ("warning", logging.WARNING),
    ("nonsense", logging.INFO),
])
def test_level_from_settings(monkeypatch, raw, expected):
    class _S:
        log_level = raw

    monkeypatch.setattr(
        "app.infrastructure.settings.get_settings", lambda: _S(), raising=True
    )
    assert obs.level_from_settings() == expected


# ── 访问中间件 ─────────────────────────────────────────────


def _make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def _access_records(caplog):
    return [r for r in caplog.records if r.name == "app.access"]


def test_normal_request_logged_at_info(caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    client = _make_client()
    client.get("/ping?x=1")

    recs = [r for r in _access_records(caplog) if r.levelno == logging.INFO]
    assert recs, "普通请求应记 INFO"
    ctx = recs[-1].ctx
    assert ctx["method"] == "GET"
    assert ctx["path"] == "/ping"
    assert ctx["status"] == 200
    assert ctx["query"] == "x=1"
    assert isinstance(ctx["ms"], float)


def test_health_is_quiet_at_info(caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    client = _make_client()
    client.get("/health")

    levels = {r.levelno for r in _access_records(caplog)}
    assert logging.INFO not in levels, "/health 不该在 INFO 打点（会刷屏）"
    assert logging.DEBUG in levels, "/health 在 DEBUG 下应可见"


def test_exception_logged_as_error_with_traceback(caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    client = _make_client()
    client.get("/boom")

    errors = [r for r in _access_records(caplog) if r.levelno == logging.ERROR]
    assert errors, "未处理异常应记 ERROR"
    assert errors[-1].ctx["path"] == "/boom"
    assert errors[-1].exc_info is not None
