"""解析状态检查 — 双验证: DB 状态 + MinIO parsed-data/full.md 存在性。

用法:
    python -m cli.check_status
    python -m cli.check_status --detail
"""
from __future__ import annotations

import asyncio
import logging
from argparse import ArgumentParser

from sqlalchemy import func, select

from app.interface.deps import get_container
from src.models import DocumentTask, TaskStatus

log = logging.getLogger("check")


async def _run(detail: bool) -> None:
    sessionmaker = get_container().get_db_sessionmaker()
    async with sessionmaker() as s:
        total = (await s.execute(select(func.count()).select_from(DocumentTask))).scalar()
        if total == 0:
            log.info("DB 中没有记录")
            return

        rows = (
            await s.execute(
                select(DocumentTask.status, func.count().label("cnt")).group_by(DocumentTask.status)
            )
        ).all()

        log.info("=" * 45)
        log.info("  DB 状态统计")
        log.info("=" * 45)
        for st in (TaskStatus.PARSED, TaskStatus.PROCESSING, TaskStatus.PENDING, TaskStatus.FAILED):
            cnt = next((r.cnt for r in rows if r.status == st), 0)
            log.info("  %-12s %d", st, cnt)

        parsed = (
            await s.execute(select(DocumentTask).where(DocumentTask.status == TaskStatus.PARSED))
        ).scalars().all()

        log.info("")
        log.info("=" * 45)
        log.info("  双验证: status=parsed 的 MinIO 一致性")
        log.info("=" * 45)

        minio = get_container().get_minio()

        valid = lost = 0
        for task in sorted(parsed, key=lambda x: x.updated_at or x.created_at, reverse=True):
            if minio.check_parsed_exists(task.md5):
                valid += 1
            else:
                lost += 1
                log.warning("  [数据丢失] %s  status=parsed 但 MinIO parsed-data/%s/full.md 不存在",
                            task.original_name, task.md5)
                if detail:
                    log.info("    task_id=%s, raw=%s, parsed=%s",
                             task.id, task.raw_minio_path, task.parsed_minio_path)

        if lost == 0:
            log.info("  %d 个全部一致 (MinIO full.md 均存在)", valid)
        else:
            log.warning("  %d 个一致, %d 个数据丢失（下次扫描会自动重新提交）", valid, lost)

        if detail:
            log.info("")
            log.info("=" * 45)
            log.info("  全量明细")
            log.info("=" * 45)
            all_tasks = (
                await s.execute(select(DocumentTask).order_by(DocumentTask.created_at))
            ).scalars().all()
            for t in all_tasks:
                log.info("  %-12s %-30s md5=%s", t.status, t.original_name[:28], t.md5)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = ArgumentParser(description="解析状态检查")
    ap.add_argument("--detail", action="store_true", help="显示明细")
    args = ap.parse_args()
    asyncio.run(_run(args.detail))


if __name__ == "__main__":
    main()
