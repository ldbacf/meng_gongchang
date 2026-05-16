"""
文件夹扫描提交器 — 扫描 pdf/ + json/ 配对，去重后提交 MinerU。

自动识别两种目录结构:
  子目录模式: my_data/pdf/*.pdf + my_data/json/*.json
  平铺模式:   my_data/*.pdf + my_data/*.json (同目录)

用法:
    uv run python scripts/scan_submit.py
    uv run python scripts/scan_submit.py --dir ./my_data
    uv run python scripts/scan_submit.py --dry-run
"""

import asyncio
import hashlib
import logging
import sys
from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import fitz
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.config import MINERU_BATCH_SIZE, MINIO_META_BUCKET, MINIO_RAW_BUCKET
from src.db import async_session, engine
from src.key_manager import TokenExhausted, get_key_manager
from src.mineru_client import submit_batch
from src.minio_client import check_parsed_exists, init_buckets, upload_meta_json, upload_raw_pdf
from src.models import Base, DocumentTask, TaskStatus
from src.redis_client import enqueue_batch
from sqlalchemy import select

# ── 日志 ──────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent.parent / "log"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scan")

BATCH_INTERVAL = 2.0  # 批间等待秒数


# ── 扫描配对 ───────────────────────────────────────────

def scan_pairs(data_dir: Path) -> list[dict]:
    pdf_dir = data_dir / "pdf"
    json_dir = data_dir / "json"
    if not pdf_dir.exists():
        pdf_dir = data_dir
        json_dir = data_dir
        mode = "flat"
    else:
        mode = "subdir"
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        log.error("%s 下没有 PDF 文件", pdf_dir)
        sys.exit(1)
    pairs = []
    missing = 0
    for pdf in pdfs:
        jf = json_dir / f"{pdf.stem}.json"
        if not jf.exists():
            missing += 1
            continue
        pairs.append({"stem": pdf.stem, "pdf_path": pdf, "json_path": jf})
    log.info("[%s] %d 个 PDF, 配对 %d 个, 缺 json 跳过 %d 个", mode, len(pdfs), len(pairs), missing)
    return pairs


async def dedup_filter(pairs: list[dict]) -> list[dict]:
    result = []
    skip_done = 0
    skip_running = 0
    for pair in tqdm(pairs, desc="MD5 查重", ncols=80):
        data = pair["pdf_path"].read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        async with async_session() as s:
            row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == md5))).scalar_one_or_none()
            if row:
                if row.status == TaskStatus.PARSED and check_parsed_exists(md5):
                    skip_done += 1
                    continue
                if row.status == TaskStatus.PROCESSING:
                    skip_running += 1
                    continue
                row.status = TaskStatus.PENDING
                row.error_msg = None
                await s.commit()
        pages = fitz.open(stream=data, filetype="pdf").page_count
        result.append({
            "stem": pair["stem"], "pdf_path": pair["pdf_path"],
            "json_path": pair["json_path"],
            "pdf_data": data, "json_data": pair["json_path"].read_bytes(),
            "md5": md5, "pages": pages,
        })
    if skip_done:
        log.info("跳过 %d 个已完成", skip_done)
    if skip_running:
        log.info("跳过 %d 个处理中", skip_running)
    return result


async def submit_all(files: list[dict]):
    km = get_key_manager()
    files.sort(key=lambda x: x["pages"], reverse=True)

    groups = defaultdict(list)
    for fi in files:
        try:
            t = km.acquire(fi["pages"])
            km.release(t, fi["pages"])
            groups[t].append(fi)
        except TokenExhausted as e:
            log.warning("%s: 额度不足 -> %s", fi["stem"], e)
            async with async_session() as s:
                row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == fi["md5"]))).scalar_one_or_none()
                if row:
                    row.status = TaskStatus.FAILED
                    row.error_msg = str(e)
                await s.commit()

    total = len(files)
    pbar = tqdm(total=total, desc="提交进度", ncols=80)
    submitted = 0
    failed = 0

    for token, flist in groups.items():
        for i in range(0, len(flist), MINERU_BATCH_SIZE):
            chunk = flist[i:i + MINERU_BATCH_SIZE]
            mbatch = []
            for fi in chunk:
                rp = upload_raw_pdf(fi["md5"], fi["pdf_path"].name, fi["pdf_data"])
                mp = upload_meta_json(fi["md5"], fi["json_path"].name, fi["json_data"])
                async with async_session() as s:
                    row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == fi["md5"]))).scalar_one_or_none()
                    if row:
                        row.raw_minio_path = f"{MINIO_RAW_BUCKET}/{rp}"
                        row.meta_minio_path = f"{MINIO_META_BUCKET}/{mp}"
                        row.status = TaskStatus.PENDING
                    else:
                        s.add(DocumentTask(
                            md5=fi["md5"], original_name=fi["pdf_path"].name,
                            raw_minio_path=f"{MINIO_RAW_BUCKET}/{rp}",
                            meta_minio_path=f"{MINIO_META_BUCKET}/{mp}",
                            status=TaskStatus.PENDING,
                        ))
                    await s.commit()
                mbatch.append({"name": fi["pdf_path"].name, "data": fi["pdf_data"], "md5": fi["md5"]})

            try:
                bid, md5s = await submit_batch(mbatch, token=token)
                async with async_session() as s:
                    for m in md5s:
                        row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == m))).scalar_one_or_none()
                        if row:
                            row.batch_id = bid
                            row.status = TaskStatus.PROCESSING
                    await s.commit()
                await enqueue_batch(bid, md5s, token=token)
                submitted += len(chunk)
                pbar.update(len(chunk))
                pbar.set_postfix_str(f"成功{submitted} 失败{failed}")
            except Exception as e:
                log.error("一批 %d 个提交失败: %s", len(chunk), e)
                failed += len(chunk)
                async with async_session() as s:
                    for fi in chunk:
                        row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == fi["md5"]))).scalar_one_or_none()
                        if row:
                            row.status = TaskStatus.FAILED
                            row.error_msg = str(e)
                        await s.commit()
                pbar.update(len(chunk))
                pbar.set_postfix_str(f"成功{submitted} 失败{failed}")

            # 批间等待，减缓限流
            if i + MINERU_BATCH_SIZE < len(flist):
                await asyncio.sleep(BATCH_INTERVAL)

    pbar.close()

    # 额度用尽的也算失败
    used_all = sum(1 for f in files if f["pages"] < 1)
    total_failed = failed + (total - submitted - failed)
    log.info("提交完成: %d 成功, %d 失败 (共 %d)", submitted, total - submitted, total)
    log.info("额度报告:\n%s", km.usage_report())


async def main():
    ap = ArgumentParser()
    ap.add_argument("--dir", "-d", default=".", type=str)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pages-only", action="store_true")
    args = ap.parse_args()
    data_dir = Path(args.dir).resolve()

    log.info("=" * 50)
    log.info("文件夹扫描提交器 启动")
    log.info("数据目录: %s", data_dir)
    log.info("日志文件: %s", log_file)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_buckets()

    pairs = scan_pairs(data_dir)
    if not pairs:
        return

    to_submit = await dedup_filter(pairs)
    if not to_submit:
        log.info("没有需要提交的文件")
        return

    total_pages = sum(f["pages"] for f in to_submit)
    log.info("待提交: %d 个, 共 %d 页", len(to_submit), total_pages)
    if args.pages_only or args.dry_run:
        for f in to_submit:
            log.info("  %s: %d 页", f["stem"], f["pages"])
        if args.pages_only:
            return
        log.info("DRY RUN 结束, 共 %d 页", total_pages)
        return

    await submit_all(to_submit)
    log.info("完成, Worker 会自动轮询处理")


if __name__ == "__main__":
    asyncio.run(main())
