"""cli 共享工具 — 脚本日志 / chunk JSON 扫描 / 断点续跑（收敛各脚本重复实现）。"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "log"


def setup_script_logging(
    name: str, *, no_file: bool = False, tqdm_write: bool = False,
) -> logging.Logger:
    """控制台 + 文件双 handler（替代各脚本内联的 _setup_logging）。

    `tqdm_write=True`：控制台经 `tqdm.write` 输出，避免撕裂进度条（长批次脚本用）。
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S",
    ))
    if tqdm_write:
        from tqdm import tqdm

        console.emit = lambda record: tqdm.write(console.format(record), file=sys.stderr)
    root.addHandler(console)

    if not no_file:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(_LOG_DIR / f"{name}_{ts}.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-5s  [%(name)s]  %(message)s",
        ))
        root.addHandler(fh)
    return logging.getLogger(name)


def scan_json_files(data_dir: Path, limit: int | None = None) -> list[Path]:
    """目录下非 checkpoint 的 .json 文件（按名排序）。"""
    files = sorted(
        f for f in data_dir.iterdir()
        if f.suffix == ".json" and not f.name.startswith(".checkpoint")
    )
    return files[:limit] if limit else files


def load_checkpoint(data_dir: Path, tag: str) -> dict[str, str]:
    ckpt = data_dir / f".checkpoint_{tag}.json"
    if ckpt.exists():
        try:
            with open(ckpt, "r", encoding="utf-8") as f:
                return json.load(f).get("completed", {})
        except Exception:
            return {}
    return {}


def save_checkpoint(data_dir: Path, tag: str, completed: dict[str, str]) -> None:
    ckpt = data_dir / f".checkpoint_{tag}.json"
    with open(ckpt, "w", encoding="utf-8") as f:
        json.dump(
            {"completed": completed, "total": len(completed)},
            f, ensure_ascii=False, indent=2,
        )


def mark_done(completed: dict[str, str], stem: str) -> None:
    completed[stem] = datetime.now(timezone.utc).isoformat()
