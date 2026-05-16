"""
解析状态检查 — 双验证: DB 状态 + MinIO parsed-data/full.md 存在性

用法:
    uv run python scripts/check_status.py
    uv run python scripts/check_status.py --detail    # 显示每个文件明细
"""

import asyncio
import logging
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import func, select

from src.db import async_session, engine
from src.minio_client import check_parsed_exists
from src.models import Base, DocumentTask, TaskStatus

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("check")


async def main():
    ap = ArgumentParser(description="解析状态检查")
    ap.add_argument("--detail", action="store_true", help="显示明细")
    args = ap.parse_args()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as s:
        total = (await s.execute(select(func.count()).select_from(DocumentTask))).scalar()

        if total == 0:
            log.info("DB 中没有记录")
            return

        # 各状态统计
        rows = (
            await s.execute(
                select(DocumentTask.status, func.count().label("cnt"))
                .group_by(DocumentTask.status)
            )
        ).all()

        log.info("=" * 45)
        log.info("  DB 状态统计")
        log.info("=" * 45)
        status_order = [TaskStatus.PARSED, TaskStatus.PROCESSING, TaskStatus.PENDING, TaskStatus.FAILED]
        for st in status_order:
            cnt = next((r.cnt for r in rows if r.status == st), 0)
            log.info("  %-12s %d", st, cnt)

        log.info("")

        # parsed 的逐文件双验证
        parsed = (
            await s.execute(
                select(DocumentTask).where(DocumentTask.status == TaskStatus.PARSED)
            )
        ).scalars().all()

        log.info("=" * 45)
        log.info("  双验证: status=parsed 的 MinIO 一致性")
        log.info("=" * 45)

        valid = 0
        lost = 0
        for task in sorted(parsed, key=lambda x: x.updated_at or x.created_at, reverse=True):
            exists = check_parsed_exists(task.md5)
            if exists:
                valid += 1
            else:
                lost += 1
                log.warning("  [数据丢失] %s  status=parsed 但 MinIO parsed-data/%s/full.md 不存在",
                            task.original_name, task.md5)
                if args.detail:
                    log.info("    task_id=%s, raw=%s, parsed=%s",
                              task.id, task.raw_minio_path, task.parsed_minio_path)

        if lost == 0:
            log.info("  %d 个全部一致 (MinIO full.md 均存在)", valid)
        else:
            log.warning("  %d 个一致, %d 个数据丢失", valid, lost)
            log.warning("  丢失的文件下次扫描时会自动重新提交")

        # 明细
        if args.detail:
            log.info("")
            log.info("=" * 45)
            log.info("  全量明细")
            log.info("=" * 45)
            all_tasks = (
                await s.execute(select(DocumentTask).order_by(DocumentTask.created_at))
            ).scalars().all()
            for t in all_tasks:
                log.info("  %-12s %-30s md5=%s",
                          t.status, t.original_name[:28], t.md5)


asyncio.run(main())
