"""离线切分 — 从 MinIO 读取已解析产物，三粒度切分，输出 chunk JSON（可选上传）。

切分入口复用 domain 唯一入口 `app.domain.chunking.chunk_document.chunk_document`
（与在线 `index_document` 图同源 → 产物同构，A-5.4）。

健壮性: 断点续跑 / 单条失败隔离 / MinIO 重试 / 原子写入 / 空 full.md 跳过。

用法:
    python -m cli.run_chunker
    python -m cli.run_chunker --md5 abc123,def456 --limit 20
    python -m cli.run_chunker --out-dir ./chunks --upload
    python -m cli.run_chunker --upload-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from cli._common import setup_script_logging

_PARSED_BUCKET = "parsed-data"
_META_BUCKET = "doc-meta"


class CheckpointManager:
    def __init__(self, out_dir: Path):
        self.path = out_dir / ".checkpoint.json"
        self.completed: dict[str, str] = {}
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.completed = json.load(f).get("completed", {})
            except Exception:
                self.completed = {}

    def is_done(self, md5: str) -> bool:
        return md5 in self.completed

    def mark_done(self, md5: str) -> None:
        self.completed[md5] = datetime.now(timezone.utc).isoformat()

    def flush(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "completed": self.completed,
                "total_completed": len(self.completed),
                "last_update": datetime.now(timezone.utc).isoformat(),
            }, f, ensure_ascii=False, indent=2)


def _fetch_with_retry(client, bucket: str, path: str, logger, max_retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.get_object(bucket, path)
            data = resp.read()
            resp.close()
            resp.release_conn()
            return data
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                logger.debug("Retry %d/%d for %s/%s in %ds: %s", attempt + 1, max_retries, bucket, path, delay, e)
                time.sleep(delay)
    raise RuntimeError(f"Failed after {max_retries} retries for {bucket}/{path}: {last_err}")


def fetch_document(minio_client, md5: str, logger) -> tuple[str | None, list | None, dict | None, str]:
    """拉取一篇文档三个数据源 → (full_md, content_list_v2, meta, uuid)。单源失败不影响其他。"""
    uuid = ""
    try:
        data = _fetch_with_retry(minio_client, _PARSED_BUCKET, f"{md5}/full.md", logger)
        full_md_text = data.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("[%s] full.md 拉取失败: %s — 跳过此文档", md5, e)
        return None, None, None, ""

    content_list_v2 = None
    try:
        objs = list(minio_client.list_objects(_PARSED_BUCKET, prefix=f"{md5}/", recursive=True))
        v2_file = [o.object_name for o in objs if "content_list_v2" in o.object_name]
        if v2_file:
            fname = v2_file[0].split("/", 1)[1] if "/" in v2_file[0] else v2_file[0]
            uuid = fname.replace("_content_list_v2.json", "")
            data = _fetch_with_retry(minio_client, _PARSED_BUCKET, v2_file[0], logger)
            content_list_v2 = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("[%s] content_list_v2.json 拉取失败: %s — 仅用 full.md", md5, e)

    meta = None
    try:
        meta_objs = list(minio_client.list_objects(_META_BUCKET, prefix=f"{md5}/", recursive=True))
        json_files = [o.object_name for o in meta_objs if o.object_name.endswith(".json")]
        if json_files:
            data = _fetch_with_retry(minio_client, _META_BUCKET, json_files[0], logger)
            meta = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("[%s] doc-meta JSON 拉取失败: %s — 元信息为空", md5, e)

    return full_md_text, content_list_v2, meta, uuid


def atomic_write_json(data: dict, path: Path) -> None:
    """先写 .tmp 再 rename，防断电/中断损坏。"""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp.")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def scan_md5_list(minio_client, limit: int | None = None) -> list[str]:
    md5_list = []
    for obj in minio_client.list_objects(_PARSED_BUCKET, recursive=False):
        md5 = obj.object_name.rstrip("/")
        if md5:
            md5_list.append(md5)
            if limit and len(md5_list) >= limit:
                break
    return md5_list


def upload_phase(out_dir: Path, minio_client, logger) -> None:
    from src.minio_client import chunk_json_exists, upload_chunk_json

    json_files = sorted(f for f in os.listdir(out_dir) if f.endswith(".json") and f != ".checkpoint.json")
    if not json_files:
        logger.info("无待上传文件")
        return

    logger.info("=" * 54)
    logger.info("开始上传 %d 个 chunk JSON 到 MinIO chunks 桶", len(json_files))
    stats = {"success": 0, "skipped": 0, "failed": 0}
    failed_files: list[tuple[str, str]] = []
    t_start = time.time()

    with tqdm(total=len(json_files), desc="上传", unit="个", ncols=120) as pbar:
        for fname in json_files:
            fpath = out_dir / fname
            pbar.set_postfix_str(fname[:60])
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                uuid = data.get("uuid", "")
                if not uuid:
                    logger.warning("[%s] JSON 缺少 uuid 字段，跳过", fname)
                    stats["skipped"] += 1
                    pbar.update(1)
                    continue
            except Exception as e:
                logger.error("[%s] 读取失败: %s", fname, e)
                stats["failed"] += 1
                failed_files.append((fname, str(e)))
                pbar.update(1)
                continue

            try:
                if chunk_json_exists(uuid):
                    stats["skipped"] += 1
                    pbar.update(1)
                    continue
            except Exception:
                pass

            try:
                json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                upload_chunk_json(uuid, json_bytes)
                stats["success"] += 1
            except Exception as e:
                logger.error("[%s] 上传失败: %s", fname, e)
                stats["failed"] += 1
                failed_files.append((fname, str(e)))
            pbar.update(1)

    logger.info("上传完成 — 耗时 %.1fs", time.time() - t_start)
    logger.info("成功 %d / 跳过 %d (已存在) / 失败 %d", stats["success"], stats["skipped"], stats["failed"])
    if failed_files:
        logger.warning("上传失败 (%d 个):", len(failed_files))
        for fname, err in failed_files[:20]:
            logger.warning("  %s: %s", fname, err)


def main() -> None:
    parser = argparse.ArgumentParser(description="MinerU Chunk 切分工具（复用 domain 唯一入口）")
    parser.add_argument("--md5", type=str, help="切分指定 MD5（逗号分隔）")
    parser.add_argument("--limit", type=int, default=None, help="最多切分 N 篇")
    parser.add_argument("--out-dir", type=str, default="./chunks", help="输出目录")
    parser.add_argument("--resume", action="store_true", help="启用断点续跑（默认开启）")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    parser.add_argument("--upload", action="store_true", help="切分后上传全部 JSON 到 MinIO chunks 桶")
    parser.add_argument("--upload-only", action="store_true", help="只上传本地已有 JSON")
    parser.add_argument("--no-log-file", action="store_true", help="不写日志文件")
    args = parser.parse_args()

    logger = setup_script_logging("chunker", no_file=args.no_log_file, tqdm_write=True)

    from app.domain.chunking.chunk_document import chunk_document
    from app.interface.deps import get_container

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    minio_client = get_container().get_minio().client

    if args.upload_only:
        upload_phase(out_dir, minio_client, logger)
        return

    if args.md5:
        md5_list = [m.strip() for m in args.md5.split(",") if m.strip()]
        logger.info("指定 %d 篇文档", len(md5_list))
    else:
        logger.info("扫描 parsed-data 桶…")
        md5_list = scan_md5_list(minio_client, args.limit)
        logger.info("桶内共 %d 篇已解析", len(md5_list))

    if not md5_list:
        logger.info("无待切分文档")
        return

    checkpoint = CheckpointManager(out_dir)
    resume = args.resume or not args.no_resume
    if resume:
        pending_md5s = [m for m in md5_list if not checkpoint.is_done(m)]
        skipped = len(md5_list) - len(pending_md5s)
        if skipped:
            logger.info("断点续跑：跳过 %d 篇已完成，剩余 %d 篇待处理", skipped, len(pending_md5s))
    else:
        pending_md5s = list(md5_list)

    if not pending_md5s:
        logger.info("全部已完成，无需处理")
        return

    stats = {"success": 0, "skipped_no_fullmd": 0, "failed": 0}
    chunk_counts: dict[str, int] = {}
    failed_docs: list[tuple[str, str]] = []
    total_chunks = max_chunks = 0
    max_chunks_md5 = ""
    t_start = time.time()

    with tqdm(total=len(pending_md5s), desc="切分", unit="篇", ncols=120) as pbar:
        for md5 in pending_md5s:
            pbar.set_postfix_str(f"md5={md5[:12]} Ch=?")
            full_md, cl_v2, meta, uuid = fetch_document(minio_client, md5, logger)
            if full_md is None:
                stats["skipped_no_fullmd"] += 1
                pbar.update(1)
                continue

            try:
                result = chunk_document(md5, full_md, cl_v2, meta)
            except Exception:
                err_msg = traceback.format_exc()
                logger.error("[%s] 切分异常:\n%s", md5, err_msg)
                stats["failed"] += 1
                failed_docs.append((md5, str(err_msg).splitlines()[-1]))
                pbar.update(1)
                continue

            doc_id = result["doc_id"]
            result["uuid"] = uuid
            n_chunks = result["total_chunks"]
            fpath = out_dir / (f"{uuid}.json" if uuid else f"{doc_id}_{md5[:8]}.json")

            try:
                atomic_write_json(result, fpath)
            except Exception as e:
                logger.error("[%s] 写入失败: %s", md5, e)
                stats["failed"] += 1
                failed_docs.append((md5, f"write error: {e}"))
                pbar.update(1)
                continue

            stats["success"] += 1
            total_chunks += n_chunks
            if n_chunks > max_chunks:
                max_chunks, max_chunks_md5 = n_chunks, md5
            for ch in result["chunks"]:
                chunk_counts[ch["level"]] = chunk_counts.get(ch["level"], 0) + 1
            checkpoint.mark_done(md5)
            checkpoint.flush()
            pbar.set_postfix_str(f"md5={md5[:12]} Ch={n_chunks}")
            pbar.update(1)

    logger.info("=" * 54)
    logger.info("切分完成 — 耗时 %.1fs", time.time() - t_start)
    logger.info("成功 %d / 跳过 %d (缺full.md) / 失败 %d",
                stats["success"], stats["skipped_no_fullmd"], stats["failed"])
    logger.info("L0: %d | L1: %d | L2: %d | 总计 chunk: %d",
                chunk_counts.get("L0", 0), chunk_counts.get("L1", 0),
                chunk_counts.get("L2", 0), total_chunks)
    if stats["success"] > 0:
        logger.info("平均: %.1f chunk/篇 | 最大: %d chunk (%s)",
                    total_chunks / stats["success"], max_chunks, max_chunks_md5[:12])
    if failed_docs:
        logger.warning("失败文档 (%d 篇):", len(failed_docs))
        for md5, err in failed_docs[:20]:
            logger.warning("  %s: %s", md5, err)
    logger.info("输出目录: %s", out_dir.resolve())

    if args.upload:
        upload_phase(out_dir, minio_client, logger)


if __name__ == "__main__":
    main()
