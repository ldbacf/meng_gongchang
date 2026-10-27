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

## reload 为什么不用 uvicorn 自带的（重要）

uvicorn 的 `--reload` 在 Windows 上有**静默失效**的真实故障：
`BaseReload.restart()` 用 `os.kill(child_pid, signal.CTRL_C_EVENT)` 让子进程退出，

    def restart(self):
        if sys.platform == "win32":
            os.kill(self.process.pid, signal.CTRL_C_EVENT)
            sys.stdout.write(" ")      # workaround：没 console 时这行也没用
        self.process.join()            # ← 无超时

而 `CTRL_C_EVENT` 只能送达**与发送者共享同一 console 且同进程组**的进程。
经 `uv run` 包装、ConPTY（Windows Terminal / VS Code 终端）、或非交互方式启动时，
这个条件不成立 → 事件送不到 → `join()` 永久阻塞，reloader 卡死，
此后再改文件都不会重启（但 watchfiles 那边仍然打印 `Reloading...`，极具误导性）。

更糟的是父进程不执行 lifespan、`log_config=None` 又没有 handler，
那行 `Reloading...` 常被直接丢弃 —— 「reload 在工作但不重启」和「reload 根本没工作」
看起来一模一样（本项目实测排查了两轮才定位）。

改用 `watchfiles.run_process`：它用 `multiprocessing(spawn).Process` 起子进程，
终止走 `Process.terminate()`，**不依赖 console / 进程组**。
`worker.py` 早已是这个做法，两个入口至此一致。

用法:
    uv run medrag-api                          # 生产/单进程
    uv run medrag-api --reload                 # 本地开发，改代码自动重启
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


def _run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """真正跑 uvicorn（reload 时作为被监视的子进程 target 调用）。

    **必须是模块级函数**：`watchfiles.run_process` 用 spawn 起子进程，
    target 与 kwargs 都要能被 pickle 引用；闭包/lambda、或「靠模块级全局变量
    传参」都会失效 —— 子进程是全新解释器，看不到父进程对全局变量的修改。
    """
    _configure_event_loop()

    import uvicorn

    # loop="none" 的作用见模块 docstring：
    # 让 uvicorn 不接管事件循环，回落到上面设的 SelectorEventLoopPolicy。
    # 因为我们不再用 uvicorn 的 reload 子进程机制，uvicorn 始终跑在**当前进程**里，
    # asyncio_loop_factory 永远走 use_subprocess=False 那条（win32 上硬编码 Proactor），
    # 不显式关掉就会拿到 Proactor 而崩。
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        loop="none",
        # log_config=None → 不让 uvicorn 用它自己的 LOGGING_CONFIG 覆盖我们的 JSON 日志。
        # 否则它会在 import 之后把 uvicorn.access 重设回 INFO，输出非 JSON 的
        # `INFO: 127.0.0.1 - "GET ... 200 OK"`，和业务日志混在一起、还把真正的日志淹掉。
        log_config=None,
    )


def _backend_root():
    """backend/ 目录（reload 只监听代码，避免盯着 .venv 与 data/）。"""
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


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

    if not args.reload:
        _run_server(args.host, args.port)
        return

    # ── reload：交给 watchfiles，不用 uvicorn 的（原因见模块 docstring）──
    from watchfiles import run_process

    app_dir = _backend_root() / "app"
    cli_dir = _backend_root() / "cli"

    # 父进程也要有日志：否则「改动已被检测到、正在重启」这类信息全被丢弃，
    # 出问题时完全无法判断 reloader 到底活着没有（这正是排查时的最大障碍）。
    _configure_event_loop()
    from app.infrastructure.observability.logger import get_logger, setup_logging

    setup_logging()
    log = get_logger("app.reload")
    log.info("reload 已开启，监视 %s 与 %s", app_dir, cli_dir)

    run_process(
        app_dir,
        cli_dir,
        target=_run_server,
        target_type="function",
        # kwargs 会随 spawn 传给子进程（不是全局变量），这是传 host/port 的唯一可靠方式
        kwargs={"host": args.host, "port": args.port},
        # debounce 默认 1600ms：编辑器保存时常产生多个事件，太快会连续重启几次
        callback=lambda changes: log.warning(
            "检测到改动，重启服务: %s",
            ", ".join(sorted({p for _c, p in changes})),
        ),
    )


if __name__ == "__main__":
    main()
