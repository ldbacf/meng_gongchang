"""批量导入 chunk JSON 到 Elasticsearch — 复用 `app.infrastructure.indexer.es_bulk_write`（唯一写入 seam）。

原 `scripts/import_es.py` 内联 `helpers.bulk`；收敛后统一经 `es_bulk_write`
（自动建索引 + `_id=chunk_id` + refresh，与在线 `es_write` 节点同源）。

用法: python -m cli.import_es --dir ./chunks [--limit N] [--batch 500] [--no-resume]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tqdm import tqdm

from app.infrastructure.settings import get_settings
from cli._common import (
    load_checkpoint,
    mark_done,
    save_checkpoint,
    scan_json_files,
    setup_script_logging,
)


def _chunks_from_file(filepath: Path) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f).get("chunks", [])


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入 ES（复用 es_bulk_write）")
    parser.add_argument("--dir", type=str, default="./chunks", help="chunk JSON 目录")
    parser.add_argument("--limit", type=int, default=None, help="限制文件数")
    parser.add_argument("--batch", type=int, default=500, help="每批量大小")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    parser.add_argument("--es-index", type=str, default=get_settings().es_index, help="目标 ES 索引")
    args = parser.parse_args()

    logger = setup_script_logging("import_es")
    data_dir = Path(args.dir)
    files = scan_json_files(data_dir, args.limit)
    if not files:
        logger.warning("无待导入文件: %s", data_dir)
        return

    completed = {} if args.no_resume else load_checkpoint(data_dir, "es")
    if completed:
        logger.info("断点续跑：已有 %d 篇已导入", len(completed))

    pending = [f for f in files if f.stem not in completed]
    if not pending:
        logger.info("全部已完成，无需导入")
        return
    logger.info("共 %d 个文件待导入 → 索引 %s", len(pending), args.es_index)

    from app.infrastructure.indexer import es_bulk_write

    stats = {"docs": 0, "errors": 0}
    t_start = time.time()
    batch: list[dict] = []

    with tqdm(total=len(pending), desc="导入 ES", unit="篇", ncols=120) as pbar:
        for fpath in pending:
            try:
                batch.extend(_chunks_from_file(fpath))
            except Exception as e:
                logger.error("读取失败 %s: %s", fpath.stem, e)
                stats["errors"] += 1
                pbar.update(1)
                continue

            if len(batch) >= args.batch:
                try:
                    stats["docs"] += es_bulk_write(args.es_index, batch)
                except Exception as e:
                    logger.error("批量写入异常: %s", e)
                    stats["errors"] += 1
                batch = []

            mark_done(completed, fpath.stem)
            save_checkpoint(data_dir, "es", completed)
            pbar.set_postfix_str(f"docs={stats['docs']}")
            pbar.update(1)

        if batch:
            try:
                stats["docs"] += es_bulk_write(args.es_index, batch)
            except Exception as e:
                logger.error("批量写入异常: %s", e)

    logger.info("导入完成 — 耗时 %.1fs | docs %d | 错误 %d 篇",
                time.time() - t_start, stats["docs"], stats["errors"])


if __name__ == "__main__":
    main()
