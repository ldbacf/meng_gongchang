"""index_document 子图 — 单文档索引链（thread_id=batch:{batch_id}:doc:{md5}）。

read_markdown → chunk_document(domain 唯一入口) → embed_batch → es_write → milvus_write。

- 每个节点末尾显式投影写 DB（pipeline_steps/status）——图是唯一写入方，
  "图状态与 DB 双写一致" = at-least-once 收敛（副作用幂等，Milvus 先删后插 / ES _id 覆盖）。
- 节点级 `retry_policy`（显式 retry_on MineruTransientError，C4）；Fatal 短路。
- 子图内**禁用 interrupt**（手动 ainvoke 的子图 interrupt 会冒泡成畸形父状态）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.application.graphs.nodes._task import (
    ensure_parsed,
    load_task,
    mark_failed,
    mark_indexing,
    mark_ready,
    update_steps,
)
from app.application.graphs.state import IndexDocState
from app.domain.knowledge_base import resolve_kb_kind
from app.infrastructure.adapters.embedding_http import EmbeddingServiceError
from app.infrastructure.adapters.mineru import MineruTransientError
from src.indexer import es_bulk_write


async def load_context(state: IndexDocState) -> dict:
    """查 task + KB 上下文（kb_kind/es_index/milvus_collection/title）；→INDEXING。

    retry/resume 场景 task 被 reset 回 PENDING：先 ensure_parsed 补跳
    PENDING→PROCESSING→PARSED，再 PARSED→INDEXING（状态机合法链）。
    """
    task = await load_task(state["md5"])
    if task is None:
        return {"fatal": True, "error": {"step": "load_context", "type": "Fatal", "message": "task 不存在"}}
    await ensure_parsed(state["md5"])
    await mark_indexing(state["md5"])
    await update_steps(state["md5"], "chunking", "running")
    from app.interface.deps import get_container

    kb = None
    if task.kb_id:
        from sqlalchemy import select

        from src.models import KnowledgeBase

        async with get_container().get_db_sessionmaker()() as session:
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == task.kb_id))
            kb = r.scalar_one_or_none()
    out = {
        "kb_kind": resolve_kb_kind(kb if kb else task).value,
        "title": Path(task.original_name).stem,
    }
    if kb:
        out["es_index"] = kb.es_index
        out["milvus_collection"] = kb.milvus_collection
    return out


async def read_markdown(state: IndexDocState) -> dict:
    from app.interface.deps import get_container

    full_md = get_container().get_minio().read_parsed_markdown(state["md5"])
    return {"parsed_full_md": full_md}


async def chunk_document_node(state: IndexDocState) -> dict:
    from app.domain.chunking.chunk_document import chunk_document

    result = chunk_document(
        state["md5"], state["parsed_full_md"], None, {}, title=state.get("title", ""),
    )
    chunks = result["chunks"]
    await update_steps(state["md5"], "chunking", "done", chunk_count=len(chunks))
    return {"chunks": chunks}


async def embed_batch(state: IndexDocState) -> dict:
    from app.interface.deps import get_container

    model = get_container().get_embedder()
    # bge-m3 推理（local）/ HTTP 请求（remote）均为同步阻塞，移出 event loop。
    # model.embed_documents 既适配 EmbeddingFactory（local）也适配 HttpEmbeddingPort（remote）。
    vectors = await asyncio.to_thread(
        model.embed_documents, [c["content"] for c in state["chunks"]]
    )
    await update_steps(state["md5"], "embedding", "done", count=len(vectors))
    return {"vectors": [list(v) for v in vectors]}


async def es_write(state: IndexDocState) -> dict:
    es_index = state["es_index"]
    written = es_bulk_write(es_index, state["chunks"])
    await update_steps(state["md5"], "es_write", "done", target_index=es_index, count=written)
    return {"es_written": written}


async def milvus_write(state: IndexDocState) -> dict:
    from app.interface.deps import get_container

    mv = get_container().get_milvus()
    collection = mv.ensure_collection(state["milvus_collection"])
    # 向量附回 chunk（upsert_batch 按 chunk_id 先删后插幂等）
    rows = []
    for chunk, vec in zip(state["chunks"], state["vectors"]):
        row = dict(chunk)
        row["vector"] = vec
        rows.append(row)
    written = mv.upsert_batch(collection, rows)
    await update_steps(
        state["md5"], "milvus", "done",
        target_collection=state["milvus_collection"], count=written,
    )
    await mark_ready(state["md5"])  # INDEXING→READY
    from src.ws_manager import broadcast_doc_update

    task = await load_task(state["md5"])
    if task:
        await broadcast_doc_update(task)
    return {"milvus_written": written}


_TRANSIENT = RetryPolicy(
    retry_on=lambda e: isinstance(e, (MineruTransientError, EmbeddingServiceError)),
    max_attempts=3,
)


def build_index_document_graph(checkpointer):
    """构建 index_document 子图（compile 必挂 checkpointer，C3）。"""
    g = StateGraph(IndexDocState)
    g.add_node("load_context", load_context, retry_policy=_TRANSIENT)
    g.add_node("read_markdown", read_markdown, retry_policy=_TRANSIENT)
    g.add_node("chunk_document", chunk_document_node)
    g.add_node("embed_batch", embed_batch, retry_policy=_TRANSIENT)
    g.add_node("es_write", es_write, retry_policy=_TRANSIENT)
    g.add_node("milvus_write", milvus_write, retry_policy=_TRANSIENT)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "read_markdown")
    g.add_edge("read_markdown", "chunk_document")
    g.add_edge("chunk_document", "embed_batch")
    g.add_edge("embed_batch", "es_write")
    g.add_edge("es_write", "milvus_write")
    g.add_edge("milvus_write", END)
    return g.compile(checkpointer=checkpointer)
