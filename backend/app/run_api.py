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
    ap.add_argument(
        "--reload",
        action="store_true",
        help="改代码自动重启（仅本地开发；worker 也支持 --reload）",
    )
    args = ap.parse_args()

    _configure_event_loop()

    import uvicorn

    # ── reload 与 loop 的组合在 Windows 上是互斥的 ──────────────────────
    #
    # 不用 reload：uvicorn 走**同进程**，asyncio_loop_factory(use_subprocess=False)
    # 在 win32 上硬编码返回 ProactorEventLoop → psycopg async 不可用。
    # 所以必须 loop="none" 让它不接管循环、回落到上面的 SelectorEventLoopPolicy。
    #
    # 用 reload：uvicorn 必然走**子进程**（Supervisor 派生子进程加载 app），
    # asyncio_loop_factory(use_subprocess=True) 反而返回 SelectorEventLoop —— 天然正确。
    # 此时若还传 loop="none"，子进程里没人设 policy，又会拿到 ProactorEventLoop 而崩。
    # 所以：reload 时不要传 loop，交给 uvicorn 自己按子进程路径选。
    run_kwargs: dict = {
        "host": args.host,
        "port": args.port,
        # log_config=None → 不让 uvicorn 用它自己的 LOGGING_CONFIG 覆盖我们的 JSON 日志。
        # 否则它会在 import 之后把 uvicorn.access 重设回 INFO，输出非 JSON 的
        # `INFO: 127.0.0.1 - "GET ... 200 OK"`，和业务日志混在一起、还把真正的日志淹掉。
        "log_config": None,
    }
    if args.reload:
        run_kwargs.update(
            reload=True,
            # 只监听代码目录。传 backend/ 会把 .venv（5GB）、data/（12GB）也纳入监视，
            # watchfiles 遍历成本高且容易漏事件。
            reload_dirs=[str(_backend_root() / "app"), str(_backend_root() / "cli")],
        )
    else:
        run_kwargs["loop"] = "none"

    uvicorn.run("app.main:app", **run_kwargs)


def _backend_root():
    """backend/ 目录（reload 只监听代码，避免盯着 .venv 与 data/）。"""
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    main()
