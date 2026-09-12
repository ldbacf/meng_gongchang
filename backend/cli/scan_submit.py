"""文件夹扫描提交器 — 扫描 pdf/ + json/ 配对，去重后提交 MinerU。

原 `scripts/scan_submit.py` 的 `submit_all()` 内联了 token 分组 / 分批 / reserve-commit-refund /
enqueue 全套编排（与 `SubmissionService` 重复）；收敛后提交统一经
`container.get_submission_service().submit()`（唯一提交路径，O-3.5）。

自动识别两种目录结构:
  子目录: my_data/pdf/*.pdf + my_data/json/*.json
  平铺:   my_data/*.pdf + my_data/*.json

用法:
    python -m cli.scan_submit [--dir .] [--dry-run] [--pages-only]
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from argparse import ArgumentParser
from pathlib import Path

import fitz
from sqlalchemy import select
from tqdm import tqdm

from app.infrastructure.settings import get_settings
from cli._common import setup_script_logging
from src.models import DocumentTask, TaskStatus

log = logging.getLogger("scan")


def scan_pairs(data_dir: Path) -> list[dict]:
    pdf_dir = data_dir / "pdf"
    json_dir = data_dir / "json"
    if not pdf_dir.exists():
        pdf_dir = json_dir = data_dir
        mode = "flat"
    else:
        mode = "subdir"
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        log.error("%s 下没有 PDF 文件", pdf_dir)
        raise SystemExit(1)
    pairs, missing = [], 0
    for pdf in pdfs:
        jf = json_dir / f"{pdf.stem}.json"
        if not jf.exists():
            missing += 1
            continue
        pairs.append({"stem": pdf.stem, "pdf_path": pdf, "json_path": jf})
    log.info("[%s] %d 个 PDF, 配对 %d 个, 缺 json 跳过 %d 个", mode, len(pdfs), len(pairs), missing)
    return pairs


async def _dedup_filter(pairs: list[dict]) -> list[dict]:
    """MD5 查重 + 上传 raw/meta 到 MinIO + 建/重置 DocumentTask（提交前的前置）。"""
    from app.interface.deps import get_container

    container = get_container()
    sessionmaker = container.get_db_sessionmaker()
    minio = container.get_minio()
    s_cfg = get_settings()
    result, skip_done, skip_running = [], 0, 0

    for pair in tqdm(pairs, desc="MD5 查重", ncols=80):
        data = pair["pdf_path"].read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        async with sessionmaker() as s:
            row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == md5))).scalar_one_or_none()
            if row:
                if row.status == TaskStatus.PARSED and minio.check_parsed_exists(md5):
                    skip_done += 1
                    continue
                if row.status == TaskStatus.PROCESSING:
                    skip_running += 1
                    continue
                row.reset(reason="rescan")
                row.error_msg = None
                await s.commit()

        pages = fitz.open(stream=data, filetype="pdf").page_count
        json_data = pair["json_path"].read_bytes()
        rp = minio.upload_raw_pdf(md5, pair["pdf_path"].name, data)
        mp = minio.upload_meta_json(md5, pair["json_path"].name, json_data)

        async with sessionmaker() as s:
            row = (await s.execute(select(DocumentTask).where(DocumentTask.md5 == md5))).scalar_one_or_none()
            if row:
                row.raw_minio_path = f"{s_cfg.minio_raw_bucket}/{rp}"
                row.meta_minio_path = f"{s_cfg.minio_meta_bucket}/{mp}"
                row.reset(reason="resubmit")
            else:
                s.add(DocumentTask(
                    md5=md5, original_name=pair["pdf_path"].name,
                    raw_minio_path=f"{s_cfg.minio_raw_bucket}/{rp}",
                    meta_minio_path=f"{s_cfg.minio_meta_bucket}/{mp}",
                    status=TaskStatus.PENDING,
                ))
            await s.commit()

        result.append({
            "stem": pair["stem"], "pdf_path": pair["pdf_path"],
            "name": pair["pdf_path"].name, "data": data,
            "md5": md5, "pages": pages,
        })

    if skip_done:
        log.info("跳过 %d 个已完成", skip_done)
    if skip_running:
        log.info("跳过 %d 个处理中", skip_running)
    return result


async def _submit(files: list[dict]) -> None:
    """统一经 SubmissionService（token 分组/分批/reserve-commit-refund/enqueue 全在里面）。"""
    from app.interface.deps import get_container

    svc = get_container().get_submission_service()
    results = await svc.submit(files)
    ok = sum(1 for r in results if r["ok"])
    log.info("提交完成: %d 成功, %d 失败 (共 %d)", ok, len(results) - ok, len(results))
    for r in results:
        if not r["ok"]:
            log.warning("  %s: %s", r["md5"][:8], r["error"])
    log.info("额度报告:\n%s", await get_container().get_key_manager().usage_report())


async def _main() -> None:
    ap = ArgumentParser()
    ap.add_argument("--dir", "-d", default=".", type=str)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pages-only", action="store_true")
    args = ap.parse_args()
    data_dir = Path(args.dir).resolve()

    log.info("=" * 50)
    log.info("文件夹扫描提交器 启动")
    log.info("数据目录: %s", data_dir)

    from app.interface.deps import get_container

    await get_container().get_minio().init_buckets()

    pairs = scan_pairs(data_dir)
    if not pairs:
        return

    to_submit = await _dedup_filter(pairs)
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

    await _submit(to_submit)
    log.info("完成, Worker 会自动轮询处理")


def main() -> None:
    setup_script_logging("scan")
    asyncio.run(_main())


if __name__ == "__main__":
    main()
