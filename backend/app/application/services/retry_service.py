"""RetryService — retry 改 checkpoint 恢复（O-3.4）。

- **索引失败**（MinerU 已完成）：`task.reset(PENDING)` + 发 **resume 队列消息**
  （mode="resume"，batch_id=原 batch_id——checkpoint thread 键），worker claim 后
  `ainvoke(初始 input)` 从 checkpoint 续跑（state.parsed 已有 → 跳过 poll；幂等重索引）。
  不经队列直接 API resume 会丢任务（API 崩溃）+ 多进程双跑——必须经队列串行化。
- **MinerU 失败**（fatal）：重新提交（SubmissionService，**新 batch_id**）+ 旧批
  `superseded` 标记——防旧批队列消息被 XAUTOCLAIM 回收后 poll 旧批 fatal 踩新状态。
- "禁止复用已消费 batch_id" = 不重发旧 MinerU 批（resume 消息是 checkpoint 续跑信号）。
"""
from __future__ import annotations

from src.models import DocumentTask, TaskStatus


class RetryService:
    def __init__(self, container):
        self._container = container

    async def retry(self, task: DocumentTask, submit_files: list[dict] | None = None) -> dict:
        """按失败类型重试。

        submit_files: MinerU 失败重提交时的文件信息 [{"name","data","md5","pages"}]；
        无则尝试从 MinIO 重新读取（调用方负责提供）。
        """
        steps = task.pipeline_steps or {}
        mineru_failed = (steps.get("mineru") or {}).get("status") == "failed"
        queue = self._container.get_queue()
        vault = self._container.get_token_vault()

        if mineru_failed:
            # MinerU 失败 → 重新提交（新 batch_id）+ 旧批 superseded
            old_batch = task.batch_id
            if old_batch:
                await queue.mark_superseded(old_batch)
            async with self._container.get_db_sessionmaker()() as session:
                from sqlalchemy import select

                from src.models import DocumentTask as _DT

                r = await session.execute(select(_DT).where(_DT.id == task.id))
                t = r.scalar_one()
                t.reset(reason="retry_mineru")
                t.error_msg = None
                await session.commit()

            # 从 MinIO raw-docs 读回原始 PDF 重新提交（无文件则仅重置）
            files = submit_files or await self._read_raw_pdf(task)
            if files:
                from app.application.services.document_submission import SubmissionService

                submission = SubmissionService(self._container)
                return {
                    "kind": "resubmit",
                    "results": await submission.submit(files),
                }
            return {"kind": "resubmit", "results": []}

        # 索引失败 → reset + resume 队列消息（worker 从 checkpoint 续跑）
        async with self._container.get_db_sessionmaker()() as session:
            from sqlalchemy import select

            from src.models import DocumentTask as _DT

            r = await session.execute(select(_DT).where(_DT.id == task.id))
            t = r.scalar_one()
            t.reset(reason="retry_index")
            t.error_msg = None
            await session.commit()

        token_id = await self._container.get_redis().get(f"batch:{task.batch_id}") \
            if task.batch_id else None
        if not token_id:
            token_id = vault.first_id()
        if task.batch_id:
            await queue.enqueue(task.batch_id, [task.md5], token_id or "", mode="resume")
        return {"kind": "resume", "batch_id": task.batch_id}

    async def _read_raw_pdf(self, task) -> list[dict]:
        """从 MinIO raw-docs 读回原始 PDF（MinerU 重提交用）。"""
        import fitz

        minio = self._container.get_minio()
        settings = self._container.get_settings()
        try:
            path = task.raw_minio_path or ""
            if path.startswith(f"{settings.minio_raw_bucket}/"):
                path = path[len(f"{settings.minio_raw_bucket}/"):]
            obj = minio.get_object(settings.minio_raw_bucket, path)
            data = obj.read()
            obj.close()
            obj.release_conn()
            doc = fitz.open(stream=data, filetype="pdf")
            pages = doc.page_count
            doc.close()
            return [{
                "name": task.original_name or "unknown.pdf",
                "data": data,
                "md5": task.md5,
                "pages": pages,
            }]
        except Exception:
            return []
