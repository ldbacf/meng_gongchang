"""API 启动入口 — 先设事件循环策略再起 uvicorn（Windows 必需）。

**为什么**：`container.start()` 会创建 `AsyncPostgresSaver`（langgraph checkpointer），
它经 **psycopg async** 连 PostgreSQL；而 psycopg async **不支持 Windows 的
ProactorEventLoop**（Python 3.8+ 在 Windows 的默认循环）：

    InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.

后果：直接 `uvicorn app.main:app` 起服务时，checkpointer 建不出来 → QAGraph 不可用
（`get_checkpointer()` 抛错）→ **问答功能挂掉**（启动日志会出现"警告: Postgres
checkpointer 创建失败"）。

`app.application.worker` 已在自己的入口设了 Selector；API 侧由本模块统一承担。

**注意**：不要用 `--workers`/`--reload` 起本服务——uvicorn 走子进程时会强制把策略
改回 ProactorEventLoop，checkpointer 会再次失效。需要多进程请用 docker compose
的 `backend` 服务（镜像内为 Linux，无此限制）。

用法:
    uv run medrag-api            # 或 python -m src.run_api
    uv run medrag-api --port 8080 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _configure_event_loop() -> None:
    """Windows 下切到 SelectorEventLoop（psycopg async 唯一兼容的循环）。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    ap = argparse.ArgumentParser(description="MedRAG API（含 Windows 事件循环修正）")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    _configure_event_loop()

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
