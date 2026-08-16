"""Worker — 阶段 3 起迁至 `app.application.worker`（独立进程驱动 IngestionGraph）。

本模块保留 `run_worker` 名字作兼容转发（旧手动脚本 `python -m src.worker`）；
生产入口用 `uv run pipeline-worker`（pyproject → `app.application.worker:main`）。
"""
from __future__ import annotations

from app.application.worker import main as run_worker  # noqa: F401

if __name__ == "__main__":
    run_worker()
