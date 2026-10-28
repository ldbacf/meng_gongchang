"""索引节点 DB 投影的**幂等性** —— 图是 at-least-once，节点会被重跑。

## 为什么需要这一组

真实事故：一份 PDF 上传后界面卡在「索引中」25 分钟不动。

链路是三个 bug 叠加，其中直接触发点是这里 —— `mark_indexing` 无条件推进状态：

    InvalidStatusTransition: 非法状态迁移: indexing → indexing

`index_document` 子图会因崩溃恢复 / 队列重投 / resume 从 `load_context`
重新进入，而库里状态已经是 `indexing`。状态机的迁移表里没有
`INDEXING → INDEXING` 这条边，于是抛异常；`_process_job` 抛出后消息既不
ack 也不 nack，只能等 1800s 可见性超时，表现为每轮重试固定多等 30 分钟。

节点是 at-least-once 的，所以**每个"设置状态"的 helper 都必须幂等**。
本文件锁住这条契约。

## 依赖

真实 PG（isolated_db 建临时库，不碰开发库）；无 PG 时 skip。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.application.graphs.nodes._task import (
    mark_failed,
    mark_indexing,
    mark_ready,
)
from app.infrastructure.container import AppContainer
from app.infrastructure.db.models import DocumentTask, KnowledgeBase, TaskStatus
from app.interface.deps import set_container

pytestmark = pytest.mark.usefixtures("isolated_db")


@pytest.fixture
async def task_env():
    """真实 PG 建临时 KB + task（状态由测试自己设定）。"""
    container = AppContainer(fakes={})
    set_container(container)

    kb = KnowledgeBase(
        name="幂等测试库", description="", slug=f"idem_{uuid.uuid4().hex[:8]}",
        kb_kind="generic",
        es_index=f"kb_idem_{uuid.uuid4().hex[:8]}",
        milvus_collection=f"kb_idem_{uuid.uuid4().hex[:8]}",
    )
    md5 = "idem" + uuid.uuid4().hex[:28]

    async with container.get_db_sessionmaker()() as session:
        session.add(kb)
        await session.commit()
        await session.refresh(kb)
        task = DocumentTask(
            kb_id=kb.id, md5=md5, original_name="幂等.pdf",
            raw_minio_path="raw/x.pdf", status=TaskStatus.PARSED,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

    yield container, md5

    async with container.get_db_sessionmaker()() as session:
        from sqlalchemy import delete

        await session.execute(delete(DocumentTask).where(DocumentTask.md5 == md5))
        await session.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb.id))
        await session.commit()
    set_container(None)


async def _status(container, md5: str) -> str:
    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        return r.scalar_one().status


@pytest.mark.asyncio
async def test_mark_indexing_is_idempotent(task_env):
    """PARSED→INDEXING 后再调一次不能抛（这正是线上卡死的那个迁移）。

    重入场景：子图崩溃恢复 / 队列 nack 重投 / retry resume，
    `load_context` 会再跑一遍 `mark_indexing`，此时库里已是 INDEXING。
    """
    container, md5 = task_env

    await mark_indexing(md5)
    assert await _status(container, md5) == TaskStatus.INDEXING.value

    # 第二次：不得抛 InvalidStatusTransition: indexing → indexing
    await mark_indexing(md5)
    assert await _status(container, md5) == TaskStatus.INDEXING.value

    # 第三次也一样（模拟多次重投）
    await mark_indexing(md5)
    assert await _status(container, md5) == TaskStatus.INDEXING.value


@pytest.mark.asyncio
async def test_mark_indexing_does_not_downgrade_ready(task_env):
    """已 READY 的文档不该被重跑的子图拉回 INDEXING。

    `dispatch_index` 本来会按 READY 跳过，但重投路径上节点仍可能被执行；
    若这里把 READY 打回 INDEXING，文档会从"可检索"变回"索引中"，
    对用户是可见的功能倒退。
    """
    container, md5 = task_env

    await mark_indexing(md5)
    await mark_ready(md5)
    assert await _status(container, md5) == TaskStatus.READY.value

    await mark_indexing(md5)
    assert await _status(container, md5) == TaskStatus.READY.value, (
        "READY 被 mark_indexing 打回了 INDEXING"
    )


@pytest.mark.asyncio
async def test_mark_ready_is_idempotent(task_env):
    """INDEXING→READY 重复调用不抛（milvus_write 重跑的第二条路径）。"""
    container, md5 = task_env

    await mark_indexing(md5)
    await mark_ready(md5)
    assert await _status(container, md5) == TaskStatus.READY.value

    await mark_ready(md5)  # 不得抛
    assert await _status(container, md5) == TaskStatus.READY.value


@pytest.mark.asyncio
async def test_mark_failed_from_indexing_still_works(task_env):
    """幂等短路不能挡住正常失败路径：INDEXING → FAILED 仍须可达。"""
    container, md5 = task_env

    await mark_indexing(md5)
    await mark_failed(md5, "embedding 超时")

    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        t = r.scalar_one()
        assert t.status == TaskStatus.FAILED.value
        assert t.error_msg == "embedding 超时"


@pytest.mark.asyncio
async def test_helpers_tolerate_missing_task():
    """task 不存在时返回 None / 静默返回，不抛 —— 节点靠 load_context 报 fatal。"""
    container = AppContainer(fakes={})
    set_container(container)
    try:
        assert await mark_indexing("no-such-md5") is None
        await mark_ready("no-such-md5")  # 不抛
    finally:
        set_container(None)
