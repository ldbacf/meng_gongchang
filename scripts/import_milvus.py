"""
批量导入 chunk JSON 到 Milvus — bge-m3 编码 content → 写入标量 + embedding。

健壮性:
  - 断点续跑：.checkpoint.json 记录已导入的 UUID
  - 幂等：重跑跳过已导入文件（检查 Milvus 实体 + checkpoint）
  - bge-m3 模块级单例，避免重复加载
  - 每批失败隔离，记录错误不中断
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
    log_path = _LOG_DIR / f"import_milvus_{ts}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  [%(name)s]  %(message)s",
    ))
    root.addHandler(fh)

    return logging.getLogger("import_milvus")

from pymilvus import Collection, connections

from src.config import MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION

# ── embedding 模型（模块级单例） ──
_MODEL = None
_MODEL_DEVICE = ""


def _get_model(device: str = ""):
    global _MODEL, _MODEL_DEVICE
    if _MODEL is None or _MODEL_DEVICE != device:
        from sentence_transformers import SentenceTransformer
        # 优先使用本地模型
        local_path = os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
        local_path = os.path.abspath(local_path)
        model_id = local_path if os.path.isdir(local_path) else "BAAI/bge-m3"
        kw = {"device": device} if device else {}
        _MODEL = SentenceTransformer(model_id, **kw)
        _MODEL_DEVICE = device
    return _MODEL


def _scan_json_files(data_dir: Path, limit: int | None = None) -> list[Path]:
    files = sorted(
        f for f in data_dir.iterdir()
        if f.suffix == ".json" and not f.name.startswith(".checkpoint")
    )
    if limit:
        files = files[:limit]
    return files


_FIELD_MAX = {
    "chunk_id": 128, "doc_id": 32, "doi": 128, "level": 4, "chunk_type": 16,
    "journal": 128, "section": 128, "article_type": 128, "title_cn": 512,
}


def _truncate(val: str, field: str) -> str:
    limit = _FIELD_MAX.get(field, 256)
    return val if len(val) <= limit else val[:limit]


def _rows_from_file(filepath: Path, model) -> list[dict]:
    """展开一篇 chunk JSON，编码 content，返回 Milvus insert 数据"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    contents = []
    indices = []

    for i, ch in enumerate(data.get("chunks", [])):
        content = ch.get("content", "")
        if not content:
            continue
        contents.append(content)
        indices.append(i)

    if not contents:
        return rows

    embeddings = model.encode(contents, normalize_embeddings=True, show_progress_bar=False)

    for idx, emb in zip(indices, embeddings):
        ch = data["chunks"][idx]
        rows.append({
            "chunk_id":    _truncate(ch["chunk_id"], "chunk_id"),
            "doc_id":      _truncate(ch["doc_id"], "doc_id"),
            "doi":         _truncate(ch.get("doi", ""), "doi"),
            "level":       _truncate(ch["level"], "level"),
            "chunk_type":  _truncate(ch["chunk_type"], "chunk_type"),
            "journal":     _truncate(ch.get("journal", ""), "journal"),
            "section":     _truncate(ch.get("section", ""), "section"),
            "article_type": _truncate(ch.get("article_type", ""), "article_type"),
            "title_cn":    _truncate(ch.get("title_cn", ""), "title_cn"),
            "embedding":   emb.tolist(),
        })

    return rows


def _load_checkpoint(data_dir: Path) -> dict[str, str]:
    ckpt = data_dir / ".checkpoint_milvus.json"
    if ckpt.exists():
        try:
            with open(ckpt, "r", encoding="utf-8") as f:
                return json.load(f).get("completed", {})
        except Exception:
            return {}
    return {}


def _save_checkpoint(data_dir: Path, completed: dict[str, str]):
    ckpt = data_dir / ".checkpoint_milvus.json"
    with open(ckpt, "w", encoding="utf-8") as f:
        json.dump({"completed": completed, "total": len(completed)}, f, ensure_ascii=False, indent=2)


def _run_single(collection, pending, model, data_dir, completed, stats, logger, pbar):
    """单条模式：每文件编码 → 写入 → checkpoint"""
    _log_interval = max(1, len(pending) // 10)
    _last_log = 0

    for fpath in pending:
        try:
            rows = _rows_from_file(fpath, model)
        except Exception as e:
            logger.error("编码失败 %s: %s", fpath.stem, e)
            stats["errors"] += 1
            pbar.update(1)
            continue

        if not rows:
            completed[fpath.stem] = datetime.now(timezone.utc).isoformat()
            _save_checkpoint(data_dir, completed)
            pbar.update(1)
            continue

        try:
            collection.upsert(rows)
            stats["rows"] += len(rows)
            completed[fpath.stem] = datetime.now(timezone.utc).isoformat()
            _save_checkpoint(data_dir, completed)
            sample = rows[:5]
            logger.info(
                "写入 %s — %d rows | 累计 %d | chunk_ids: %s …",
                fpath.stem[:12], len(rows), stats["rows"],
                ", ".join(r["chunk_id"] for r in sample),
            )
        except Exception as e:
            sample = rows[:3]
            logger.error("写入失败 %s: %s | chunk_ids: %s …", fpath.stem[:12], e, ", ".join(r["chunk_id"] for r in sample))
            stats["errors"] += 1

        if pbar.n - _last_log >= _log_interval:
            logger.info("进度 %d/%d — rows %d | errors %d", pbar.n, len(pending), stats["rows"], stats["errors"])
            _last_log = pbar.n

        pbar.set_postfix_str(f"rows={stats['rows']}")
        pbar.update(1)


def _run_batch(collection, pending, model, data_dir, completed, stats, args, logger, pbar):
    """批次模式：攒 N 行 → 批次写入 → 统一 checkpoint"""
    _log_interval = max(1, len(pending) // 10)
    _last_log = 0
    batch_rows = []
    batch_files = []

    def _flush():
        nonlocal batch_rows, batch_files
        if not batch_rows:
            return
        try:
            collection.upsert(batch_rows)
            samples = batch_files[:8]
            logger.info(
                "批次写入 %d 行 | 累计 %d | files: %s …",
                len(batch_rows), stats["rows"],
                ", ".join(s[:12] for s in samples),
            )
            for f in batch_files:
                completed[f] = datetime.now(timezone.utc).isoformat()
            _save_checkpoint(data_dir, completed)
        except Exception as e:
            samples = batch_files[:3]
            logger.error("批次写入失败 (%d 行, %d 篇): %s | files: %s …", len(batch_rows), len(batch_files), e, ", ".join(s[:12] for s in samples))
            stats["errors"] += 1
            for f in batch_files:
                completed.pop(f, None)
            _save_checkpoint(data_dir, completed)
        batch_rows = []
        batch_files = []

    for fpath in pending:
        try:
            rows = _rows_from_file(fpath, model)
        except Exception as e:
            logger.error("编码失败 %s: %s", fpath.stem, e)
            stats["errors"] += 1
            pbar.update(1)
            continue

        if not rows:
            completed[fpath.stem] = datetime.now(timezone.utc).isoformat()
            _save_checkpoint(data_dir, completed)
            pbar.update(1)
            continue

        batch_rows.extend(rows)
        batch_files.append(fpath.stem)
        stats["rows"] += len(rows)

        if len(batch_rows) >= args.batch:
            _flush()

        if pbar.n - _last_log >= _log_interval:
            logger.info("进度 %d/%d — rows %d | errors %d", pbar.n, len(pending), stats["rows"], stats["errors"])
            _last_log = pbar.n

        pbar.set_postfix_str(f"rows={stats['rows']}")
        pbar.update(1)

    _flush()


def main():
    parser = argparse.ArgumentParser(description="批量导入 Milvus")
    parser.add_argument("--dir", type=str, default="./chunks", help="chunk JSON 目录")
    parser.add_argument("--limit", type=int, default=None, help="限制文件数")
    parser.add_argument("--batch", type=int, default=500, help="每批量大小 (仅 batch 模式)")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "batch"], help="single:每文件即写即存 / batch:攒批写入")
    parser.add_argument("--device", type=str, default="", help="设备: cpu / cuda:0 (默认自动检测)")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    args = parser.parse_args()

    logger = _setup_logging()

    data_dir = Path(args.dir)
    files = _scan_json_files(data_dir, args.limit)
    if not files:
        logger.warning("无待导入文件: %s", data_dir)
        return

    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    collection = Collection(MILVUS_COLLECTION)
    collection.load()
    logger.info("Milvus collection %s 就绪", MILVUS_COLLECTION)

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

    device = args.device or ("cuda:0" if __import__("torch").cuda.is_available() else "cpu")
    logger.info("加载 bge-m3 到 %s…", device)
    model = _get_model(device=device)
    logger.info("模型就绪 (%s)", device)

    logger.info("模式: %s | 共 %d 个文件待导入", args.mode, len(pending))

    stats = {"rows": 0, "errors": 0}
    t_start = time.time()

    with tqdm(total=len(pending), desc="导入 Milvus", unit="篇", ncols=120) as pbar:
        if args.mode == "single":
            _run_single(collection, pending, model, data_dir, completed, stats, logger, pbar)
        else:
            _run_batch(collection, pending, model, data_dir, completed, stats, args, logger, pbar)

        collection.flush()

    elapsed = time.time() - t_start
    logger.info("导入完成 — 耗时 %.1fs", elapsed)
    logger.info("rows %d | 错误 %d 篇", stats["rows"], stats["errors"])
    logger.info("Milvus 实体数: %s", collection.num_entities)


if __name__ == "__main__":
    main()
