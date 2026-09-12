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


def setup_logging(level: int = logging.INFO) -> None:
    """把根 logger 配为 JSON 单行输出（幂等，可重复调用）。"""
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # 压低第三方库噪音
    for name in ("uvicorn.access", "uvicorn.error", "httpcore", "httpx", "elastic_transport", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in _OFFICIAL_MARKERS:
        logging.getLogger(name).setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
