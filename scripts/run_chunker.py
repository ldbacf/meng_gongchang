"""
批量切分脚本 — 从 MinIO 读取已解析的 PDF 产物，执行三粒度切分，输出 JSON。

健壮性:
  - 断点续跑：.checkpoint.json 记录已完成的 MD5，中断重跑自动跳过
  - 单条失败隔离：异常不中断整体流程，错误记录到日志
  - 结构化日志：同时输出到控制台（INFO，tqdm.write 防撕裂）+ 文件（DEBUG，含 traceback）
  - MinIO 重试：每个数据源独立重试 3 次，指数退避
  - 原子写入：先写 .tmp 再 rename，防断电损坏
  - 输入校验：空 full.md 跳过，缺 article_id 兜底

用法:
    uv run python scripts/run_chunker.py
    uv run python scripts/run_chunker.py --md5 abc123,def456
    uv run python scripts/run_chunker.py --limit 20
    uv run python scripts/run_chunker.py --out-dir ./chunks --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.minio_client import get_minio
from src.chunker import chunk_document

# ═══════════════════════════════════════════════════════════════
# 日志配置 — 双输出（控制台 tqdm.write + 文件）
# ═══════════════════════════════════════════════════════════════

_LOG_DIR = Path(__file__).resolve().parent.parent / "log"


def _setup_logging(no_file: bool = False) -> logging.Logger:
    """配置根 logger：控制台 INFO + 文件 DEBUG"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # 控制台 — INFO（用 tqdm.write 写入，避免撕裂进度条）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S",
    ))
    console.emit = lambda record: tqdm.write(
        console.format(record), file=sys.stderr,
    )
    root.addHandler(console)

    if not no_file:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = _LOG_DIR / f"chunker_{ts}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-5s  [%(name)s]  %(message)s",
        ))
        root.addHandler(file_handler)

    return logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 断点管理
# ═══════════════════════════════════════════════════════════════


class CheckpointManager:
    """管理断点文件，支持中断续跑"""

    def __init__(self, out_dir: Path):
        self.path = out_dir / ".checkpoint.json"
        self.completed: dict[str, str] = {}  # md5 → 完成时间
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.completed = data.get("completed", {})
            except Exception:
                self.completed = {}

    def is_done(self, md5: str) -> bool:
        return md5 in self.completed

    def mark_done(self, md5: str):
        self.completed[md5] = datetime.now(timezone.utc).isoformat()

    def flush(self):
        data = {
            "completed": self.completed,
            "total_completed": len(self.completed),
            "last_update": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# MinIO 读取（带重试）
# ═══════════════════════════════════════════════════════════════


def _minio_fetch_with_retry(
    client,
    bucket: str,
    path: str,
    max_retries: int = 3,
    logger: logging.Logger | None = None,
) -> bytes:
    """从 MinIO 拉取文件，指数退避重试"""
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
                if logger:
                    logger.debug("Retry %d/%d for %s/%s in %ds: %s", attempt + 1, max_retries, bucket, path, delay, e)
                time.sleep(delay)
    raise RuntimeError(f"Failed after {max_retries} retries for {bucket}/{path}: {last_err}")


def fetch_document(
    minio_client,
    md5: str,
    logger: logging.Logger,
) -> tuple[str | None, list | None, dict | None, str]:
    """
    从 MinIO 拉取一篇文档的三个数据源。
    返回 (full_md_text, content_list_v2, meta_dict, uuid)。
    单个数据源失败不影响其他数据源。
    """
    bucket = "parsed-data"
    meta_bucket = "doc-meta"
    uuid = ""

    # 1. full.md（必需）
    full_md_text = None
    try:
        data = _minio_fetch_with_retry(minio_client, bucket, f"{md5}/full.md", logger=logger)
        full_md_text = data.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("[%s] full.md 拉取失败: %s — 跳过此文档", md5, e)
        return None, None, None, ""

    # 2. content_list_v2.json（可选）
    content_list_v2 = None
    try:
        objs = list(minio_client.list_objects(bucket, prefix=f"{md5}/", recursive=True))
        v2_file = [o.object_name for o in objs if "content_list_v2" in o.object_name]
        if v2_file:
            # 从文件名提取 UUID: {md5}/{uuid}_content_list_v2.json
            fname = v2_file[0].split("/", 1)[1] if "/" in v2_file[0] else v2_file[0]
            uuid = fname.replace("_content_list_v2.json", "")
            data = _minio_fetch_with_retry(minio_client, bucket, v2_file[0], logger=logger)
            content_list_v2 = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("[%s] content_list_v2.json 拉取失败: %s — 仅用 full.md", md5, e)

    # 3. doc-meta JSON（可选）
    meta = None
    try:
        meta_objs = list(minio_client.list_objects(meta_bucket, prefix=f"{md5}/", recursive=True))
        json_files = [o.object_name for o in meta_objs if o.object_name.endswith(".json")]
        if json_files:
            data = _minio_fetch_with_retry(minio_client, meta_bucket, json_files[0], logger=logger)
            meta = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("[%s] doc-meta JSON 拉取失败: %s — 元信息为空", md5, e)

    return full_md_text, content_list_v2, meta, uuid


# ═══════════════════════════════════════════════════════════════
# 原子写入
# ═══════════════════════════════════════════════════════════════


def atomic_write_json(data: dict, path: Path, logger: logging.Logger):
    """先写 .tmp 再 rename，防断电/中断导致文件损坏"""
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".tmp.",
    )
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


# ═══════════════════════════════════════════════════════════════
# MD5 扫描
# ═══════════════════════════════════════════════════════════════


def scan_md5_list(minio_client, limit: int | None = None) -> list[str]:
    """扫描 parsed-data 桶，返回所有已解析的 MD5 列表"""
    md5_list = []
    for obj in minio_client.list_objects("parsed-data", recursive=False):
        md5 = obj.object_name.rstrip("/")
        if md5:
            md5_list.append(md5)
            if limit and len(md5_list) >= limit:
                break
    return md5_list


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="MinerU Chunk 切分工具")
    parser.add_argument("--md5", type=str, help="切分指定 MD5（多个用逗号分隔）")
    parser.add_argument("--limit", type=int, default=None, help="最多切分 N 篇")
    parser.add_argument("--out-dir", type=str, default="./chunks", help="输出目录（默认 ./chunks）")
    parser.add_argument("--resume", action="store_true", help="启用断点续跑（默认开启）")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑，从头处理")
    parser.add_argument("--upload", action="store_true", help="切分完成后上传全部 JSON 到 MinIO chunks 桶")
    parser.add_argument("--upload-only", action="store_true", help="只上传本地已有 JSON，不切分")
    parser.add_argument("--no-log-file", action="store_true", help="不写日志文件")
    args = parser.parse_args()

    logger = _setup_logging(no_file=args.no_log_file)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    minio_client = get_minio()

    # ── 仅上传模式
    if args.upload_only:
        upload_phase(out_dir, minio_client, logger)
        return

    # ── 确定 MD5 列表
    if args.md5:
        md5_list = [m.strip() for m in args.md5.split(",") if m.strip()]
        logger.info("指定 %d 篇文档", len(md5_list))
    else:
        logger.info("扫描 parsed-data 桶…")
        md5_list = scan_md5_list(minio_client, args.limit)
        total_in_bucket = len(md5_list)
        logger.info("桶内共 %d 篇已解析", total_in_bucket)

    if not md5_list:
        logger.info("无待切分文档")
        return

    # ── 断点
    checkpoint = CheckpointManager(out_dir)
    resume = args.resume or not args.no_resume

    pending_md5s: list[str] = []
    if resume:
        for md5 in md5_list:
            if checkpoint.is_done(md5):
                logger.debug("[%s] 已在下标中，跳过", md5)
            else:
                pending_md5s.append(md5)
        skipped_by_checkpoint = len(md5_list) - len(pending_md5s)
        if skipped_by_checkpoint > 0:
            logger.info("断点续跑：跳过 %d 篇已完成，剩余 %d 篇待处理", skipped_by_checkpoint, len(pending_md5s))
    else:
        pending_md5s = list(md5_list)

    if not pending_md5s:
        logger.info("全部已完成，无需处理")
        return

    # ── 统计
    stats = {
        "total": len(pending_md5s),
        "success": 0,
        "skipped_no_fullmd": 0,
        "failed": 0,
    }
    chunk_counts: dict[str, int] = {}
    failed_docs: list[tuple[str, str]] = []  # (md5, error_msg)
    total_chunks = 0
    max_chunks = 0
    max_chunks_md5 = ""
    t_start = time.time()

    # ── 进度条循环
    with tqdm(
        total=len(pending_md5s),
        desc="切分",
        unit="篇",
        ncols=120,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
    ) as pbar:

        for md5 in pending_md5s:
            pbar.set_postfix_str(f"md5={md5[:12]} Ch=?")

            # 拉取数据
            full_md, cl_v2, meta, uuid = fetch_document(minio_client, md5, logger)

            if full_md is None:
                stats["skipped_no_fullmd"] += 1
                pbar.update(1)
                continue

            # 切分
            try:
                result = chunk_document(md5, full_md, cl_v2, meta)
            except Exception:
                err_msg = traceback.format_exc()
                logger.error("[%s] 切分异常:\n%s", md5, err_msg)
                stats["failed"] += 1
                failed_docs.append((md5, str(err_msg).splitlines()[-1]))
                pbar.update(1)
                continue

            # 注入 uuid
            doc_id = result["doc_id"]
            result["uuid"] = uuid
            n_chunks = result["total_chunks"]

            # 确定文件名
            if uuid:
                fname = f"{uuid}.json"
            else:
                # 无 UUID 兜底（极少数情况）
                fname = f"{doc_id}_{md5[:8]}.json"
                logger.debug("[%s] 无 UUID，用兜底文件名: %s", md5, fname)
            fpath = out_dir / fname

            # 写入本地
            try:
                atomic_write_json(result, fpath, logger)
            except Exception as e:
                logger.error("[%s] 写入失败: %s", md5, e)
                stats["failed"] += 1
                failed_docs.append((md5, f"write error: {e}"))
                pbar.update(1)
                continue

            # 成功
            stats["success"] += 1
            total_chunks += n_chunks
            if n_chunks > max_chunks:
                max_chunks = n_chunks
                max_chunks_md5 = md5
            for ch in result["chunks"]:
                chunk_counts[ch["level"]] = chunk_counts.get(ch["level"], 0) + 1

            checkpoint.mark_done(md5)
            checkpoint.flush()

            pbar.set_postfix_str(f"md5={md5[:12]} Ch={n_chunks}")
            pbar.update(1)

    # ── 汇总输出
    elapsed = time.time() - t_start
    logger.info("=" * 54)
    logger.info("切分完成 — 耗时 %.1fs", elapsed)
    logger.info(
        "成功 %d / 跳过 %d (缺full.md) / 失败 %d",
        stats["success"], stats["skipped_no_fullmd"], stats["failed"],
    )
    logger.info("L0（论文级）: %d", chunk_counts.get("L0", 0))
    logger.info("L1（章节级）: %d", chunk_counts.get("L1", 0))
    logger.info("L2（表格级）: %d", chunk_counts.get("L2", 0))
    logger.info("总计 chunk: %d", total_chunks)

    if stats["success"] > 0:
        avg = total_chunks / stats["success"]
        logger.info("平均: %.1f chunk/篇 | 最大: %d chunk (%s)", avg, max_chunks, max_chunks_md5[:12])

    if failed_docs:
        logger.warning("失败文档 (%d 篇):", len(failed_docs))
        for md5, err in failed_docs[:20]:
            logger.warning("  %s: %s", md5, err)
        if len(failed_docs) > 20:
            logger.warning("  ... 共 %d 篇，详见日志文件", len(failed_docs))

    logger.info("输出目录: %s", out_dir.resolve())

    # ── 上传阶段
    if args.upload or args.upload_only:
        upload_phase(out_dir, minio_client, logger)


def upload_phase(out_dir: Path, minio_client, logger: logging.Logger):
    """上传本地 chunk JSON 到 MinIO chunks 桶"""
    from src.minio_client import upload_chunk_json, chunk_json_exists

    json_files = sorted(
        f for f in os.listdir(out_dir)
        if f.endswith(".json") and f != ".checkpoint.json"
    )
    if not json_files:
        logger.info("无待上传文件")
        return

    logger.info("=" * 54)
    logger.info("开始上传 %d 个 chunk JSON 到 MinIO chunks 桶", len(json_files))

    stats = {"success": 0, "skipped": 0, "failed": 0}
    failed_files: list[tuple[str, str]] = []
    t_start = time.time()

    with tqdm(
        total=len(json_files),
        desc="上传",
        unit="个",
        ncols=120,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
    ) as pbar:

        for fname in json_files:
            fpath = out_dir / fname
            pbar.set_postfix_str(fname[:60])

            # 读 JSON 拿 UUID
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

            # 检查 MinIO 是否已有（幂等）
            try:
                if chunk_json_exists(uuid):
                    stats["skipped"] += 1
                    pbar.update(1)
                    continue
            except Exception:
                pass  # 检查失败不阻塞，直接尝试上传

            # 上传
            try:
                json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                upload_chunk_json(uuid, json_bytes)
                stats["success"] += 1
            except Exception as e:
                logger.error("[%s] 上传失败: %s", fname, e)
                stats["failed"] += 1
                failed_files.append((fname, str(e)))

            pbar.update(1)

    # 上传汇总
    elapsed = time.time() - t_start
    logger.info("上传完成 — 耗时 %.1fs", elapsed)
    logger.info("成功 %d / 跳过 %d (已存在) / 失败 %d", stats["success"], stats["skipped"], stats["failed"])

    if failed_files:
        logger.warning("上传失败 (%d 个):", len(failed_files))
        for fname, err in failed_files[:20]:
            logger.warning("  %s: %s", fname, err)


if __name__ == "__main__":
    main()
