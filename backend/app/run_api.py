"""API 启动入口 — 在 Windows 上强制使用 SelectorEventLoop（psycopg async 要求）。

**为什么**：`container.start()` 会创建 `AsyncPostgresSaver`（langgraph checkpointer），
它经 **psycopg async** 连 PostgreSQL；而 psycopg async **不支持 Windows 的
ProactorEventLoop**：

    InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.

后果：checkpointer 建不出来 → QAGraph 不可用 → **问答功能挂掉**
（启动日志出现"警告: Postgres checkpointer 创建失败"）。

**关键坑（uvicorn ≥0.36 行为变更）**：光设 `set_event_loop_policy(...)` **不够**。
uvicorn 0.36 起移除了 `setup_event_loop()`，改为在 `Server.run()` 里把 loop_factory
显式传给 `asyncio.run(..., loop_factory=...)`；而 **`asyncio.run` 传了 loop_factory
就会完全绕过 event loop policy**。且 uvicorn 在 Windows 上把它硬编码成 Proactor：

    # uvicorn/loops/asyncio.py
    def asyncio_loop_factory(use_subprocess: bool = False):
        if sys.platform == "win32" and not use_subprocess:
            return asyncio.ProactorEventLoop      # ← 无视 policy
        return asyncio.SelectorEventLoop

所以本入口做两件事：① 设 SelectorEventLoopPolicy；② **`loop="none"`**——
`loop="none"` 时 uvicorn 返回 `loop_factory=None`，`asyncio.run` 便回落到 policy，
SelectorEventLoop 才真正生效。（`loop="auto"` / `"asyncio"` 都会拿到 ProactorEventLoop。）

`app.application.worker` 已在自己的入口设了 Selector；API 侧由本模块承担。

**注意**：不要加 `--workers`/`--reload`——子进程路径 `use_subprocess=True`，uvicorn 会
返回 SelectorEventLoop 之外的差异行为，且与本地单进程调试语义不符；需要多进程请用
docker compose 的 `backend` 服务（Linux 镜像无此限制）。

用法:
    uv run medrag-api            # 或 python -m app.run_api
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

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        # loop="none" → uvicorn 不接管事件循环，asyncio.run 回落到上面设的 policy。
        # 用默认的 "auto"/"asyncio" 会被 uvicorn 硬编码成 ProactorEventLoop（见模块 docstring）。
        loop="none",
    )


if __name__ == "__main__":
    main()
