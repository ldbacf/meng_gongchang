"""批量导入 chunk JSON 到 Milvus — 复用容器 embedder + `src.indexer.milvus_insert`。

原 `scripts/import_milvus.py` 内联 `model.encode()` + `collection.upsert()`（**第三条并行路径**）；
收敛后：编码经容器唯一 embedder（`get_embedder().embed_query/embed_documents`），
写入经 `milvus_insert` → `MilvusAdapter.upsert_batch`（按 chunk_id 先删后插 + 字段截断 + 共享 schema）。

**doc_id 口径与在线同构**：chunk JSON 已含契约 doc_id，本脚本不再重算。

用法:
    python -m cli.import_milvus --dir ./chunks [--limit N] [--batch 500]
        [--mode single|batch] [--device cpu] [--no-resume] [--collection chunks]
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

_FIELD_TITLE_FALLBACK = ("metadata", "title_cn")


def _rows_from_file(filepath: Path) -> list[dict]:
    """展开一篇 chunk JSON → 待编码行（content 非空；title_cn 归一化到顶层）。"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for ch in data.get("chunks", []):
        content = ch.get("content", "")
        if not content:
            continue
        row = dict(ch)
        if not row.get("title_cn"):
            row["title_cn"] = (ch.get("metadata") or {}).get("title_cn", "")
        row["_content"] = content
        rows.append(row)
    return rows


def _embed(rows: list[dict], device: str = ""):
    """经容器 embedder 批量编码 content → 写回 row['vector']（唯一工厂，不内联模型）。"""
    from app.interface.deps import get_container

    model = get_container().get_embedder()
    vectors = model.embed_documents([r["_content"] for r in rows])
    for r, v in zip(rows, vectors):
        r["vector"] = list(v)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入 Milvus（复用容器 embedder + milvus_insert）")
    parser.add_argument("--dir", type=str, default="./chunks", help="chunk JSON 目录")
    parser.add_argument("--limit", type=int, default=None, help="限制文件数")
    parser.add_argument("--batch", type=int, default=500, help="每批量大小（batch 模式）")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "batch"])
    parser.add_argument("--device", type=str, default="", help="设备 cpu / cuda:0（经容器 embedder）")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    parser.add_argument("--collection", type=str, default=get_settings().milvus_collection)
    args = parser.parse_args()

    logger = setup_script_logging("import_milvus")
    data_dir = Path(args.dir)
    files = scan_json_files(data_dir, args.limit)
    if not files:
        logger.warning("无待导入文件: %s", data_dir)
        return

    completed = {} if args.no_resume else load_checkpoint(data_dir, "milvus")
    if completed:
        logger.info("断点续跑：已有 %d 篇已导入", len(completed))

    pending = [f for f in files if f.stem not in completed]
    if not pending:
        logger.info("全部已完成，无需导入")
        return

    from src.indexer import milvus_insert

    logger.info("模式: %s | 共 %d 个文件 → collection %s", args.mode, len(pending), args.collection)
    stats = {"rows": 0, "errors": 0}
    t_start = time.time()
    batch_rows: list[dict] = []
    batch_files: list[str] = []

    def _flush():
        nonlocal batch_rows, batch_files
        if not batch_rows:
            return
        try:
            stats["rows"] += milvus_insert(args.collection, batch_rows)
            for f in batch_files:
                mark_done(completed, f)
            save_checkpoint(data_dir, "milvus", completed)
        except Exception as e:
            logger.error("批次写入失败 (%d 行): %s", len(batch_rows), e)
            stats["errors"] += 1
        batch_rows, batch_files = [], []

    with tqdm(total=len(pending), desc="导入 Milvus", unit="篇", ncols=120) as pbar:
        for fpath in pending:
            try:
                rows = _embed(_rows_from_file(fpath))
            except Exception as e:
                logger.error("编码失败 %s: %s", fpath.stem, e)
                stats["errors"] += 1
                pbar.update(1)
                continue

            if not rows:
                mark_done(completed, fpath.stem)
                save_checkpoint(data_dir, "milvus", completed)
                pbar.update(1)
                continue

            if args.mode == "batch":
                batch_rows.extend(rows)
                batch_files.append(fpath.stem)
                if len(batch_rows) >= args.batch:
                    _flush()
            else:
                try:
                    stats["rows"] += milvus_insert(args.collection, rows)
                    mark_done(completed, fpath.stem)
                    save_checkpoint(data_dir, "milvus", completed)
                except Exception as e:
                    logger.error("写入失败 %s: %s", fpath.stem, e)
                    stats["errors"] += 1

            pbar.set_postfix_str(f"rows={stats['rows']}")
            pbar.update(1)

        _flush()

    logger.info("导入完成 — 耗时 %.1fs | rows %d | 错误 %d 篇",
                time.time() - t_start, stats["rows"], stats["errors"])


if __name__ == "__main__":
    main()
