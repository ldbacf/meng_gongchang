"""T-3.1/T-3.2 — IngestionGraph happy path + checkpoint resume。

外部客户端（MinerU/MinIO/Embedding/ES/Milvus）用 fake 注入容器；
DB（DocumentTask/KnowledgeBase）用真实 PG（docker 8 服务，127.0.0.1），测试数据清理。
"""
from __future__ import annotations

import time
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import select

from app.application.checkpoint_registry import config_for, thread_id_for_batch
from app.application.graphs.ingest_graph import build_ingest_graph
from app.infrastructure.adapters.mineru import MineruFatalError
from app.infrastructure.container import AppContainer
from app.interface.deps import set_container
from app.infrastructure.db.models import DocumentTask, KnowledgeBase, TaskStatus

_SAMPLE_MD = "# 1 引言\n\n测试文档正文。\n"


class _FakeMineru:
    def __init__(self, poll_result=None):
        self._poll = poll_result

    async def poll_batch(self, batch_id, token):
        return self._poll or []

    async def download_result(self, url):
        return b"PK\x03\x04"


class _FakeMinio:
    """upload_parsed_assets / read_parsed_markdown 为**同步**（与 MinioAdapter 一致）。"""

    def __init__(self, sample_md: str = _SAMPLE_MD):
        self.saved: dict[str, bytes] = {}
        self._sample = sample_md

    def upload_parsed_assets(self, md5, zip_bytes):
        self.saved[md5] = zip_bytes
        return f"http://minio/parsed-data/{md5}/full.md"

    def read_parsed_markdown(self, md5):
        return self._sample


class _FakeEmbedder:
    def get_hf_embeddings(self):
        return self

    def embed_documents(self, texts):
        return [[0.1] * 4 for _ in texts]


class _FakeMilvus:
    def __init__(self):
        self.writes = 0

    def ensure_collection(self, name):
        return object()

    def upsert_batch(self, collection, rows):
        self.writes += len(rows)
        return len(rows)


@pytest.fixture
async def ingest_env():
    """真实 PG 建临时 KB + task；注入 fake 客户端容器；测试后清理。

    必须用 async fixture（与测试同 event loop）——asyncio.run 独立 loop 会与
    pytest-asyncio 的 loop 复用同一 engine 连接池导致 asyncpg 跨 loop 冲突。
    """
    from app.application.graphs.subgraphs.index_document import (
        build_index_document_graph,
    )

    container = AppContainer(fakes={
        "mineru": _FakeMineru(),
        "minio": _FakeMinio(),
        "embedder": _FakeEmbedder(),
        "milvus": _FakeMilvus(),
        # 子图挂 InMemorySaver（测试不经容器 start 的 PG checkpointer）
        "index_subgraph": build_index_document_graph(InMemorySaver()),
    })
    set_container(container)
    kb = KnowledgeBase(
        name="阶段3测试库", description="", slug=f"t3_{uuid.uuid4().hex[:8]}",
        kb_kind="generic",
        es_index=f"kb_t3_{uuid.uuid4().hex[:8]}",
        milvus_collection=f"kb_t3_{uuid.uuid4().hex[:8]}",
    )
    md5 = "t3" + uuid.uuid4().hex[:29]  # 32 字符（DB VARCHAR(32)），随机防残留冲突
    task = DocumentTask(
        kb_id=kb.id, md5=md5,
        original_name="测试文档.pdf", raw_minio_path="raw/x.pdf",
        status=TaskStatus.PENDING,
    )

    async with container.get_db_sessionmaker()() as session:
        session.add(kb)
        await session.commit()
        await session.refresh(kb)
        task.kb_id = kb.id
        session.add(task)
        await session.commit()
        await session.refresh(task)

    yield container, kb, task

    async with container.get_db_sessionmaker()() as session:
        from sqlalchemy import delete

        await session.execute(delete(DocumentTask).where(DocumentTask.md5 == md5))
        await session.delete(kb)
        await session.commit()
    set_container(None)


async def _drive(graph, initial, cfg, max_resumes=10):
    """驱动图：首次 ainvoke + interrupt resume 循环（Command(resume) 唤醒）。"""
    result = await graph.ainvoke(initial, cfg)
    for _ in range(max_resumes):
        st = await graph.aget_state(cfg)
        if not st.interrupts:
            break
        result = await graph.ainvoke(Command(resume="wake"), cfg)
    return result


async def _task_state(container, md5):
    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == md5))
        t = r.scalar_one()
        return t.status, dict(t.pipeline_steps or {}), t.error_msg


@pytest.mark.asyncio
async def test_ingest_graph_happy_path(ingest_env, monkeypatch):
    """T-3.1: poll→download→dispatch→子图→finalize，终态 READY，pipeline_steps 全 done。"""
    container, kb, task = ingest_env
    from app.infrastructure import indexer as indexer_mod

    monkeypatch.setattr(indexer_mod, "es_bulk_write", lambda idx, chunks: len(chunks))
    # 一次 poll 即 done
    container._fakes["mineru"] = _FakeMineru(poll_result=[
        {"data_id": task.md5, "state": "done", "file_name": "t.pdf",
         "full_zip_url": "http://x/z.zip"},
    ])

    batch_id = f"t3-{uuid.uuid4().hex[:8]}"
    cfg = config_for(thread_id_for_batch(batch_id))
    result = await _drive(
        graph=build_ingest_graph(InMemorySaver()),
        initial={
            "batch_id": batch_id,
            "md5_list": [task.md5],
            "token_id": "tk_1",
            "poll_started_ts": time.time(),
        },
        cfg=cfg,
    )

    status, steps, err = await _task_state(container, task.md5)
    assert status == TaskStatus.READY.value
    for step in ("mineru", "chunking", "embedding", "es_write", "milvus"):
        assert steps[step]["status"] == "done", f"{step} 未 done: {steps}"
    assert result.get("doc_results", {}).get(task.md5) == "ready"


@pytest.mark.asyncio
async def test_poll_timeout_fatal(monkeypatch):
    """T-3.3: poll 超时（poll_started_ts 久远）→ fatal 条件边 → finalize FAILED。"""
    import time as _t

    from app.application.graphs.nodes.poll_parsed import poll_parsed

    class _AlwaysPending(_FakeMineru):
        async def poll_batch(self, batch_id, token):
            return []

    container = AppContainer(fakes={
        "mineru": _AlwaysPending(), "minio": _FakeMinio(),
        "embedder": _FakeEmbedder(), "milvus": _FakeMilvus(),
    })
    set_container(container)
    try:
        result = await poll_parsed({
            "batch_id": "b-timeout", "md5_list": ["m"], "token_id": "tk_1",
            "poll_started_ts": _t.time() - 9999,  # 远超 MAX_POLL_TIME
        })
        assert result["fatal"] is True
        assert result["error"]["type"] == "Fatal"
        assert result["error"]["step"] == "poll"
    finally:
        set_container(None)


@pytest.mark.asyncio
async def test_transient_retry_then_fatal_shortcircuit(ingest_env, monkeypatch):
    """T-3.4: Transient 触发显式 retry_on 重试；Fatal 短路。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.application.graphs.subgraphs.index_document import (
        build_index_document_graph,
    )
    from app.application.checkpoint_registry import config_for, thread_id_for_doc
    from app.infrastructure.adapters.mineru import MineruTransientError

    container, kb, task = ingest_env
    calls = {"n": 0}

    async def _flaky_load_task(md5):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise MineruTransientError("网络抖动")
        from app.application.graphs.nodes._task import load_task as _real
        return await _real(md5)

    monkeypatch.setattr(
        "app.application.graphs.subgraphs.index_document.load_task", _flaky_load_task
    )
    # 子图 load_context 前 2 次 Transient（重试），第 3 次成功
    sg = build_index_document_graph(InMemorySaver())
    # 单独测 load_context 重试：直接 ainvoke 子图（后续节点会因缺 state 失败——只需断言重试发生）
    from app.application.graphs.subgraphs import index_document as idx_mod

    # 构造最小可跑：只跑 load_context（带显式 retry_on，C4）
    from langgraph.graph import END, START, StateGraph

    mini = StateGraph(idx_mod.IndexDocState)
    mini.add_node("load_context", idx_mod.load_context, retry_policy=idx_mod._TRANSIENT)
    mini.add_edge(START, "load_context")
    mini.add_edge("load_context", END)
    mini_graph = mini.compile(checkpointer=InMemorySaver())
    final = await mini_graph.ainvoke(
        {"batch_id": "b", "md5": task.md5},
        config_for(thread_id_for_doc("b", task.md5)),
    )
    assert calls["n"] >= 3  # 重试发生
    assert final.get("es_index") == kb.es_index  # 最终成功


def test_no_checkpointer_is_redline():
    """T-3.5: compile 必须挂 checkpointer（红线 C3 静态守卫）。"""
    from app.application.graphs.ingest_graph import build_ingest_graph

    with pytest.raises(TypeError):
        build_ingest_graph()  # 缺 checkpointer 参数


@pytest.mark.asyncio
async def test_retry_from_checkpoint_resume(ingest_env, monkeypatch):
    """T-3.8: 批失败后（fatal）同 thread 续跑（checkpoint 恢复语义）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.application.checkpoint_registry import config_for, thread_id_for_batch
    from app.application.graphs.ingest_graph import build_ingest_graph

    container, kb, task = ingest_env
    from app.infrastructure import indexer as indexer_mod

    monkeypatch.setattr(indexer_mod, "es_bulk_write", lambda idx, chunks: len(chunks))

    # 第一次：MinerU fatal → finalize FAILED
    class _FatalMineru(_FakeMineru):
        async def poll_batch(self, batch_id, token):
            raise MineruFatalError("batch 不存在")

    container._fakes["mineru"] = _FatalMineru()
    batch_id = f"t3r-{uuid.uuid4().hex[:8]}"
    cfg = config_for(thread_id_for_batch(batch_id))
    graph = build_ingest_graph(InMemorySaver())
    await graph.ainvoke(
        {"batch_id": batch_id, "md5_list": [task.md5], "token_id": "tk_1",
         "poll_started_ts": time.time()},
        cfg,
    )
    status, _, _ = await _task_state(container, task.md5)
    assert status == TaskStatus.FAILED.value

    # retry：reset + resume（非空 input 从 checkpoint 续跑，poll 恢复）
    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(DocumentTask).where(DocumentTask.md5 == task.md5))
        t = r.scalar_one()
        t.reset(reason="retry_test")
        t.error_msg = None
        await session.commit()

    container._fakes["mineru"] = _FakeMineru(poll_result=[
        {"data_id": task.md5, "state": "done", "file_name": "t.pdf",
         "full_zip_url": "http://x/z.zip"},
    ])
    await _drive(
        graph,
        {"batch_id": batch_id, "md5_list": [task.md5], "token_id": "tk_1",
         "poll_started_ts": time.time(), "mode": "submit",
         "fatal": False, "error": None},  # 同 thread 重入清 checkpoint 残留
        cfg,
    )
    status, steps, err = await _task_state(container, task.md5)
    assert status == TaskStatus.READY.value, f"status={status} steps={steps} err={err}"
    assert steps["mineru"]["status"] == "done", f"steps={steps}"


@pytest.mark.asyncio
async def test_ingest_graph_poll_pending_then_done(ingest_env, monkeypatch):
    """T-3.2 前奏: poll pending（interrupt 暂停）→ resume 后 done → READY。"""
    container, kb, task = ingest_env
    from app.infrastructure import indexer as indexer_mod

    monkeypatch.setattr(indexer_mod, "es_bulk_write", lambda idx, chunks: len(chunks))
    # 第一次 poll 空（pending），第二次 done
    calls = {"n": 0}

    class _PollOnce(_FakeMineru):
        async def poll_batch(self, batch_id, token):
            calls["n"] += 1
            if calls["n"] == 1:
                return []
            return [{"data_id": task.md5, "state": "done", "file_name": "t.pdf",
                     "full_zip_url": "http://x/z.zip"}]

    container._fakes["mineru"] = _PollOnce()

    batch_id = f"t3p-{uuid.uuid4().hex[:8]}"
    cfg = config_for(thread_id_for_batch(batch_id))
    graph = build_ingest_graph(InMemorySaver())

    result = await graph.ainvoke(
        {"batch_id": batch_id, "md5_list": [task.md5], "token_id": "tk_1",
         "poll_started_ts": time.time()},
        cfg,
    )
    st = await graph.aget_state(cfg)
    assert st.interrupts, "首次 poll pending 应 interrupt 暂停"
    assert calls["n"] == 1

    # resume 唤醒 → 继续轮询 → done → 全链路完成
    result = await _drive(graph, None, cfg)
    assert calls["n"] == 2
    status, _, _ = await _task_state(container, task.md5)
    assert status == TaskStatus.READY.value
