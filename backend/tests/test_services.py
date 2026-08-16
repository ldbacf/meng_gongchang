"""T-3.6/T-3.7 — 秒传/查重（KB 内）+ 删除服务（按 doc_id + 残留对账）。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.application.services.document_deletion import (
    DeleteDocumentService,
    DocumentBusyError,
)
from app.infrastructure.container import AppContainer
from app.interface.deps import set_container
from src.models import DocumentTask, KnowledgeBase, TaskStatus


@pytest.fixture
async def kb_env():
    container = AppContainer()
    set_container(container)
    kb_a = KnowledgeBase(
        name="KB-A", description="", slug=f"ka_{uuid.uuid4().hex[:8]}",
        kb_kind="generic", es_index=f"ka_{uuid.uuid4().hex[:8]}",
        milvus_collection=f"ka_{uuid.uuid4().hex[:8]}",
    )
    kb_b = KnowledgeBase(
        name="KB-B", description="", slug=f"kb_{uuid.uuid4().hex[:8]}",
        kb_kind="generic", es_index=f"kb_{uuid.uuid4().hex[:8]}",
        milvus_collection=f"kb_{uuid.uuid4().hex[:8]}",
    )
    md5 = "sv" + uuid.uuid4().hex[:29]
    async with container.get_db_sessionmaker()() as s:
        s.add_all([kb_a, kb_b])
        await s.commit()
        await s.refresh(kb_a)
        await s.refresh(kb_b)
        task = DocumentTask(
            kb_id=kb_a.id, md5=md5, original_name="t.pdf",
            raw_minio_path="raw-docs/x.pdf",
            parsed_minio_path="http://minio/parsed-data/x/full.md",
            status=TaskStatus.PARSED,
            pipeline_steps={
                "mineru": {"status": "done", "ts": 1.0},
                "es_write": {"status": "done", "ts": 1.0, "target_index": kb_a.es_index},
                "milvus": {"status": "done", "ts": 1.0, "target_collection": kb_a.milvus_collection},
            },
        )
        s.add(task)
        await s.commit()
        await s.refresh(task)
    yield container, kb_a, kb_b, task
    async with container.get_db_sessionmaker()() as s:
        await s.execute(delete(DocumentTask).where(DocumentTask.md5 == md5))
        await s.delete(kb_a)
        await s.delete(kb_b)
        await s.commit()
    set_container(None)


@pytest.mark.asyncio
async def test_cross_kb_copy_preserves_original(kb_env):
    """T-3.6: 跨 KB 重传复制新 task，原 task kb_id 不变（禁止 reassign 归属漂移）。"""
    container, kb_a, kb_b, task = kb_env
    from src.main import _copy_across_kb

    async with container.get_db_sessionmaker()() as session:
        resp, fi = await _copy_across_kb(
            task, task.md5, "t.pdf", b"x", kb_b.id, session,
        )
        assert fi is None  # 已解析 → resume 消息，无需重新提交

    async with container.get_db_sessionmaker()() as s:
        rows = (await s.execute(
            select(DocumentTask).where(DocumentTask.md5 == task.md5)
        )).scalars().all()
        assert len(rows) == 2  # 原 task + 复制
        originals = [t for t in rows if t.kb_id == kb_a.id]
        copies = [t for t in rows if t.kb_id == kb_b.id]
        assert len(originals) == 1 and len(copies) == 1
        assert copies[0].parsed_minio_path == task.parsed_minio_path  # 保留解析引用
        assert copies[0].status == TaskStatus.PARSED.value


class _FakeESClient:
    def __init__(self):
        self.deleted: list[dict] = []
        self.remaining = 0

    def delete_by_query(self, index, body, refresh=False):
        self.deleted.append({"index": index, "body": body})
        return {"deleted": 1}

    def count(self, index, body):
        return {"count": self.remaining}


class _FakeMV:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_by_doc_ids(self, collection_name, doc_ids):
        self.deleted.append((collection_name, doc_ids))

    def count_by_doc_id(self, collection_name, doc_id):
        return 0


@pytest.mark.asyncio
async def test_delete_by_doc_id(kb_env):
    """T-3.7: 删除按 doc_id（含对账残留=0）。"""
    container, kb_a, kb_b, task = kb_env
    fake_es = _FakeESClient()
    fake_mv = _FakeMV()
    container._fakes["es"] = type("FakeES", (), {"client": fake_es})()
    container._fakes["milvus"] = fake_mv

    svc = DeleteDocumentService(container)
    result = await svc.delete(task)
    assert result["es_remaining"] == 0
    assert result["milvus_remaining"] == 0
    assert fake_es.deleted and "doc_id" in str(fake_es.deleted[0]["body"])
    assert fake_mv.deleted and task.md5[:8] in fake_mv.deleted[0][1]


@pytest.mark.asyncio
async def test_delete_busy_doc_rejected(kb_env):
    """删除非终态文档（处理中）→ DocumentBusyError。"""
    container, kb_a, kb_b, task = kb_env
    async with container.get_db_sessionmaker()() as s:
        r = await s.execute(select(DocumentTask).where(DocumentTask.id == task.id))
        t = r.scalar_one()
        t.set_status(TaskStatus.INDEXING)
        await s.commit()

    async with container.get_db_sessionmaker()() as s:
        r = await s.execute(select(DocumentTask).where(DocumentTask.id == task.id))
        busy = r.scalar_one()

    svc = DeleteDocumentService(container)
    with pytest.raises(DocumentBusyError):
        await svc.delete(busy)
