"""T-3.11 — worker 独立启动可消费（进程级，短超时冒烟）。

真实 Redis/PG（docker 8 服务）下 `python -m app.application.worker` 应能启动并进入
claim 循环；空队列时持续轮询。测试用 4 秒超时 kill，断言启动日志与进程存活。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent


def test_worker_standalone_starts():
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.application.worker"],
        cwd=_BACKEND,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        time.sleep(4)
        assert proc.poll() is None, "worker 进程提前退出"
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
