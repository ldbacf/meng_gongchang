"""后台 Worker — 多 Token 支持"""

import asyncio
import signal
import time

from sqlalchemy import select

from src.config import MAX_POLL_TIME, POLL_INTERVAL
from src.db import async_session
from src.mineru_client import download_result, poll_batch
from src.minio_client import upload_parsed_assets
from src.models import DocumentTask, TaskStatus
from src.redis_client import dequeue_batch

STATE_LABELS = {
    "waiting-file": "等待上传",
    "pending":      "排队中",
    "running":      "解析中",
    "converting":   "格式转换中",
    "done":         "已完成",
    "failed":       "失败",
}


async def _process_one_batch(batch_id: str, md5_list: list[str], token: str):
    """使用指定 token 轮询"""
    print(f"[Worker] 轮询 batch_id={batch_id} token={token[:8]}...")
    start = time.time()
    pending = set(md5_list)

    while pending and (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start

        try:
            items = await poll_batch(batch_id, token=token)
        except Exception as e:
            err_msg = str(e)
            print(f"[Worker] 查询失败 ({elapsed:.0f}s): {err_msg}")

            # 致命错误: batch 不存在 / token 失效 → 直接标记失败
            if any(kw in err_msg for kw in ("找不到任务", "没有权限", "Token 错误", "Token 过期")):
                print(f"[Worker] batch 不可恢复, 直接标记失败")
                for md5 in pending:
                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        r = await session.execute(stmt)
                        t = r.scalar_one_or_none()
                        if t:
                            t.status = TaskStatus.FAILED
                            t.error_msg = err_msg
                        await session.commit()
                return
            continue

        for item in items:
            md5 = item.get("data_id") or item.get("file_name")
            if md5 not in pending:
                continue

            state = item["state"]
            label = STATE_LABELS.get(state, state)
            fname = item.get("file_name", md5)
            print(f"[Worker] {fname}: {label} ({elapsed:.0f}s)")

            if state == "done":
                try:
                    zip_bytes = await download_result(item["full_zip_url"])
                    md_url = upload_parsed_assets(md5, zip_bytes)
                    print(f"[Worker] {fname}: 已存入 MinIO -> {md_url}")

                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        result = await session.execute(stmt)
                        task = result.scalar_one_or_none()
                        if task:
                            task.status = TaskStatus.PARSED
                            task.parsed_minio_path = md_url
                            await session.commit()
                except Exception as e:
                    print(f"[Worker] {fname}: 下载/解包失败: {e}")
                    async with async_session() as session:
                        stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                        result = await session.execute(stmt)
                        task = result.scalar_one_or_none()
                        if task:
                            task.status = TaskStatus.FAILED
                            task.error_msg = str(e)
                            await session.commit()
                pending.discard(md5)

            elif state == "failed":
                err = item.get("err_msg", "未知错误")
                print(f"[Worker] {fname}: 解析失败: {err}")
                async with async_session() as session:
                    stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
                    result = await session.execute(stmt)
                    task = result.scalar_one_or_none()
                    if task:
                        task.status = TaskStatus.FAILED
                        task.error_msg = err
                        await session.commit()
                pending.discard(md5)

    for md5 in pending:
        print(f"[Worker] {md5}: 超时")
        async with async_session() as session:
            stmt = select(DocumentTask).where(DocumentTask.md5 == md5)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                task.status = TaskStatus.FAILED
                task.error_msg = "轮询超时"
                await session.commit()


async def run_worker():
    print("[Worker] 启动，等待任务...")
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        stop = True
        print("[Worker] 收到退出信号")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop:
        try:
            job = await dequeue_batch(timeout=5)
            if job is None:
                continue
            await _process_one_batch(
                job["batch_id"],
                job["md5_list"],
                job.get("token", ""),
            )
        except Exception as e:
            print(f"[Worker] 异常: {e}")
            await asyncio.sleep(5)

    print("[Worker] 已退出")


if __name__ == "__main__":
    asyncio.run(run_worker())
