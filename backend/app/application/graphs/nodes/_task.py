"""图节点共享 DB 投影 helper — 图是 pipeline_steps/status 唯一写入方。

所有状态推进经领域状态机（DocumentTask.set_status，迁移表校验）；
重跑/resume 场景（task 被 reset 回 PENDING）用 `ensure_parsed` 补跳合法链
（PENDING→PROCESSING→PARSED），再由下游节点推进 PARSED→INDEXING→READY。
"""
from __future__ import annotations

import time

from sqlalchemy import select

from app.infrastructure.db.models import DocumentTask, TaskStatus


async def load_task(md5: str) -> DocumentTask | None:
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        return r.scalar_one_or_none()


async def update_steps(md5: str, step: str, status: str, **kwargs) -> None:
    """更新 task.pipeline_steps[step]（ts float）。

    注意：JSONB 列**就地修改不触发脏跟踪**，必须重新赋值（dict(steps) → 赋回）。
    """
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        task = r.scalar_one_or_none()
        if task:
            steps = dict(task.pipeline_steps or {})
            steps[step] = {"status": status, "ts": time.time(), **kwargs}
            task.pipeline_steps = steps  # 重新赋值触发 JSONB dirty
            await session.commit()


async def ensure_parsed(md5: str) -> DocumentTask | None:
    """重跑/resume 场景补跳：PENDING→PROCESSING→PARSED（合法迁移链）。"""
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        task = r.scalar_one_or_none()
        if task is None:
            return None
        if task.status == TaskStatus.PENDING.value:
            task.set_status(TaskStatus.PROCESSING)
        if task.status == TaskStatus.PROCESSING.value:
            task.set_status(TaskStatus.PARSED)
        await session.commit()
        return task


async def mark_indexing(md5: str) -> DocumentTask | None:
    """PARSED→INDEXING（索引开始）。

    **必须幂等**：图是 at-least-once 的，`index_document` 子图会因崩溃恢复 /
    队列重投 / resume 重跑而从 `load_context` 重新进入。此时库里已经是
    INDEXING，状态机的迁移表里 `INDEXING → INDEXING` 不是合法边，直接抛
    `InvalidStatusTransition: 非法状态迁移: indexing → indexing`。

    这个异常曾把整条流水线拖住：`_process_job` 在 `graph.ainvoke` 抛出后
    既不 ack 也不 nack（见 worker.py），消息只能靠 1800s 可见性超时重投，
    于是每次重试都固定多等 30 分钟，表现为「索引中」长时间不动。

    已经是 INDEXING 或更靠后的状态就原样返回，不重复迁移。
    """
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        task = r.scalar_one_or_none()
        if task is None:
            return None
        if task.status == TaskStatus.INDEXING.value:
            return task  # 重入：已在该阶段，无需迁移
        if task.status == TaskStatus.READY.value:
            return task  # 已完成：子图靠 dispatch_index 的 READY 判断跳过
        task.set_status(TaskStatus.INDEXING)
        await session.commit()
        return task


async def mark_ready(md5: str) -> None:
    """INDEXING→READY（索引完成）。同样幂等：已是 READY 就跳过。"""
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        task = r.scalar_one_or_none()
        if task and task.status != TaskStatus.READY.value:
            task.set_status(TaskStatus.READY)
            await session.commit()


async def mark_failed(md5: str, error: str) -> None:
    """→FAILED（任意阶段失败，迁移表允许）。"""
    from app.infrastructure.container import get_container

    async with get_container().get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        task = r.scalar_one_or_none()
        if task:
            task.set_status(TaskStatus.FAILED)
            task.error_msg = error
            await session.commit()
