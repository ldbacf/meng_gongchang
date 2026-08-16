"""SubmissionService — 统一文档提交（O-3.5，收敛 main._submit_batches 与 admin._submit_one_file）。

流程：页数排序 → 按 token 分组 → MINERU_BATCH_SIZE 分批 → reserve（占额）→ MinerU 批提交
→ commit（成功扣额）→ enqueue（mode=submit）；失败 → refund（退回）+ task FAILED。

- 额度三阶段（contract 7.10）：reserve → commit / refund。
- 队列 payload 只含 token_id（阶段 1 契约）。
- task 状态/步骤更新经领域状态机（set_status），本服务是提交路径的唯一编排方。
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from src.key_manager import TokenExhausted
from src.models import DocumentTask, TaskStatus


class SubmissionService:
    def __init__(self, container):
        self._container = container

    async def _mark_submitted(self, md5_list: list[str], batch_id: str) -> None:
        """PENDING→PROCESSING + 写 batch_id。"""
        async with self._container.get_db_sessionmaker()() as session:
            for md5 in md5_list:
                r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
                t = r.scalar_one_or_none()
                if t:
                    t.batch_id = batch_id
                    t.set_status(TaskStatus.PROCESSING)
            await session.commit()

    async def _mark_task_failed(self, md5: str, error: str) -> None:
        async with self._container.get_db_sessionmaker()() as session:
            r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
            t = r.scalar_one_or_none()
            if t:
                t.set_status(TaskStatus.FAILED)
                t.error_msg = error
                await session.commit()

    async def submit(self, files: list[dict]) -> list[dict]:
        """提交一批文件到 MinerU（统一双入口）。

        files: [{"name", "data", "md5", "pages"}]
        返回: [{"md5", "batch_id"|None, "ok": bool, "error": str|None}]
        """
        key_mgr = self._container.get_key_manager()
        vault = self._container.get_token_vault()
        mineru = self._container.get_mineru()
        queue = self._container.get_queue()
        settings = self._container.get_settings()

        # 大文件优先（减少碎片）+ 逐个 reserve 占额分组
        sorted_files = sorted(files, key=lambda x: x.get("pages", 0), reverse=True)
        groups: dict[str, list[dict]] = defaultdict(list)
        for fi in sorted_files:
            try:
                res = await key_mgr.acquire(fi["pages"])
                fi["_res"] = res
                groups[res.token_id].append(fi)
            except TokenExhausted as e:
                await self._mark_task_failed(fi["md5"], f"所有 Key 额度用完: {e}")
                fi["_error"] = str(e)

        results: list[dict] = []
        for token_id, flist in groups.items():
            token = vault.resolve(token_id)
            for i in range(0, len(flist), settings.mineru_batch_size):
                chunk = flist[i:i + settings.mineru_batch_size]
                try:
                    batch_id, md5_list = await mineru.submit_batch(
                        [{k: f[k] for k in ("name", "data", "md5")} for f in chunk],
                        token=token,
                    )
                    await self._mark_submitted(md5_list, batch_id)
                    await key_mgr.commit([f["_res"] for f in chunk])  # 提交成功 → commit
                    await queue.enqueue(batch_id, md5_list, token_id)
                    results.extend(
                        {"md5": m, "batch_id": batch_id, "ok": True, "error": None}
                        for m in md5_list
                    )
                except Exception as e:
                    await key_mgr.refund([f["_res"] for f in chunk])  # 失败退回
                    for f in chunk:
                        await self._mark_task_failed(f["md5"], str(e))
                    results.extend(
                        {"md5": f["md5"], "batch_id": None, "ok": False, "error": str(e)}
                        for f in chunk
                    )

        # 额度不足的文件（未分组）也计入结果
        for fi in sorted_files:
            if fi.get("_error"):
                results.append(
                    {"md5": fi["md5"], "batch_id": None, "ok": False, "error": fi["_error"]}
                )
        return results
