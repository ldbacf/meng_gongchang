"""结构化 JSON 日志（O-5.2 / T-5.4）——每行输出一个 JSON 对象。

- `setup_logging()`：配根 logger 为 JSON 行（level/ts/msg/logger + 可选 ctx/exc），
  并压低第三方库（uvicorn.access/httpcore/httpx/elastic_transport）噪音。
- `get_logger(name)`：返回业务 logger（经根 handler 输出 JSON）。
- 上下文：`logger.info("..", extra={"ctx": {"kb_id": ".."}})` → `ctx` 字段。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_OFFICIAL_MARKERS = {"app", "src"}

#: 环境变量 `LOG_LEVEL` 合法值 → logging 级别
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: 第三方库噪音统一压到 WARNING（即便全局是 DEBUG）
_NOISY = (
    "httpcore",
    "httpx",
    "elastic_transport",
    "urllib3",
    "asyncio",
)

#: uvicorn 自带的访问日志与 RequestLogMiddleware 重复，直接压到 WARNING
_UVICORN_ACCESS = "uvicorn.access"


def level_from_settings(default: int = logging.INFO) -> int:
    """读 `Settings.log_level`（环境变量 `LOG_LEVEL` 自动映射），非法值回落默认。

    不直接用 `os.getenv`：项目红线要求 app/ 内所有配置经 `get_settings()` 单一来源。
    """
    try:
        from app.infrastructure.settings import get_settings

        raw = get_settings().log_level
    except Exception:  # 配置尚不可用（极早期导入）时不要因日志把进程搞挂
        return default
    return _LEVELS.get(str(raw).strip().lower(), default)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "level": record.levelname,
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "msg": record.getMessage(),
            "logger": record.name,
        }
        ctx = getattr(record, "ctx", None)
        if ctx:
            entry["ctx"] = ctx
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: int | None = None) -> None:
    """把根 logger 配为 JSON 单行输出（幂等，可重复调用）。

    `level` 显式传入优先，否则读环境变量 `LOG_LEVEL`，再否则 INFO。
    """
    if level is None:
        level = level_from_settings()
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # 压低第三方库噪音
    for name in _NOISY:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    # uvicorn 的启动/关闭消息（"Uvicorn running on ..."）走 uvicorn.error，
    # 保留在 INFO 便于确认服务真的起来了；访问日志则压掉（改用 middleware）
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger(_UVICORN_ACCESS).setLevel(logging.WARNING)
    for name in _OFFICIAL_MARKERS:
        logging.getLogger(name).setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
