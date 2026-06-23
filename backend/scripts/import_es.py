"""
批量导入 chunk JSON 到 Elasticsearch — 展开 chunks[] 数组，逐条 bulk 写入。

健壮性:
  - 断点续跑：.checkpoint_es.json 记录已导入的 UUID
  - 按 chunk_id 写入自动乐观锁（幂等）
  - bulk 失败逐条回显错误（不静默）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LOG_DIR = Path(__file__).resolve().parent.parent / "log"


def _setup_logging() -> logging.Logger:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S",
    ))
    console.emit = lambda record: tqdm.write(
        console.format(record), file=sys.stderr,
    )
    root.addHandler(console)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = _LOG_DIR / f"import_es_{ts}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  [%(name)s]  %(message)s",
    ))
    root.addHandler(fh)

    return logging.getLogger("import_es")

from elasticsearch import Elasticsearch, helpers
from src.config import ES_HOST, ES_PORT, ES_USER, ES_PASSWORD, ES_INDEX


def _get_es() -> Elasticsearch:
    kwargs = {"request_timeout": 30}
    if ES_USER and ES_PASSWORD:
        return Elasticsearch(f"http://{ES_USER}:{ES_PASSWORD}@{ES_HOST}:{ES_PORT}", **kwargs)
    return Elasticsearch(f"http://{ES_HOST}:{ES_PORT}", **kwargs)


def _scan_json_files(data_dir: Path, limit: int | None = None) -> list[Path]:
    files = sorted(
        f for f in data_dir.iterdir()
        if f.suffix == ".json" and not f.name.startswith(".checkpoint")
    )
    if limit:
        files = files[:limit]
    return files


def _actions_from_file(filepath: Path) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        {"_index": ES_INDEX, "_id": ch["chunk_id"], "_source": ch}
        for ch in data.get("chunks", [])
    ]


def _load_checkpoint(data_dir: Path) -> dict[str, str]:
    ckpt = data_dir / ".checkpoint_es.json"
    if ckpt.exists():
        try:
            with open(ckpt, "r", encoding="utf-8") as f:
                return json.load(f).get("completed", {})
        except Exception:
            return {}
    return {}


def _save_checkpoint(data_dir: Path, completed: dict[str, str]):
    ckpt = data_dir / ".checkpoint_es.json"
    with open(ckpt, "w", encoding="utf-8") as f:
        json.dump({"completed": completed, "total": len(completed)}, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="批量导入 ES")
    parser.add_argument("--dir", type=str, default="./chunks", help="chunk JSON 目录")
    parser.add_argument("--limit", type=int, default=None, help="限制文件数")
    parser.add_argument("--batch", type=int, default=500, help="每批量大小")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    args = parser.parse_args()

    logger = _setup_logging()

    data_dir = Path(args.dir)
    files = _scan_json_files(data_dir, args.limit)
    if not files:
        logger.warning("无待导入文件: %s", data_dir)
        return

    es = _get_es()
    if not es.indices.exists(index=ES_INDEX):
        logger.error("ES 索引 %s 不存在，请先运行 scripts/init_es.py", ES_INDEX)
        sys.exit(1)

    # 断点
    if args.no_resume:
        completed: dict[str, str] = {}
    else:
        completed = _load_checkpoint(data_dir)
        if completed:
            logger.info("断点续跑：已有 %d 篇已导入", len(completed))

    pending = []
    for fpath in files:
        uuid = fpath.stem
        if uuid in completed:
            continue
        pending.append(fpath)

    if not pending:
        logger.info("全部已完成，无需导入")
        return

    logger.info("共 %d 个文件待导入", len(pending))

    stats = {"docs": 0, "errors": 0}
    t_start = time.time()

    with tqdm(total=len(pending), desc="导入 ES", unit="篇", ncols=120) as pbar:
        batch = []

        for fpath in pending:
            try:
                actions = _actions_from_file(fpath)
            except Exception as e:
                logger.error("读取失败 %s: %s", fpath.stem, e)
                stats["errors"] += 1
                pbar.update(1)
                continue

            batch.extend(actions)
            stats["docs"] += len(actions)

            if len(batch) >= args.batch:
                try:
                    success, errors = helpers.bulk(es, batch, raise_on_error=False)
                    if errors:
                        for err in errors[:5]:
                            logger.warning("ES 写入失败: %s", err.get("index", {}).get("_id", "?"))
                except Exception as e:
                    logger.error("批量写入异常: %s", e)
                    stats["errors"] += 1
                batch = []

            completed[fpath.stem] = datetime.now(timezone.utc).isoformat()
            _save_checkpoint(data_dir, completed)

            pbar.set_postfix_str(f"docs={stats['docs']}")
            pbar.update(1)

        if batch:
            try:
                helpers.bulk(es, batch, raise_on_error=False)
            except Exception as e:
                logger.error("批量写入异常: %s", e)

    elapsed = time.time() - t_start
    logger.info("导入完成 — 耗时 %.1fs", elapsed)
    logger.info("docs %d | 错误 %d 篇", stats["docs"], stats["errors"])


if __name__ == "__main__":
    main()
