"""retrieval — 双路初召（embed + ES BM25 + Milvus COSINE），不做 RRF（交给 fusion）。

- `recall_dual` 返回 `(milvus_hits, es_hits)`；短 query（<15 字）重复嵌入增强（在 adapter 内）。
- 检索异常 → 降级（`degraded=True`，空 hits），继续 fusion（A-4.5 明确低覆盖提示）。
"""
from __future__ import annotations

import asyncio
import time

from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step


async def retrieval(state: dict) -> dict:
    kb = state.get("kb") or {}
    search_query = state.get("rewritten_query") or state["query"]

    from src.search import recall_dual

    t0 = time.perf_counter()
    await emit_step("retrieval", "pending")

    degraded = False
    m_hits: list = []
    e_hits: list = []
    try:
        m_hits, e_hits = await asyncio.to_thread(
            recall_dual, search_query,
            es_index=kb.get("es_index"), milvus_collection=kb.get("milvus_collection"),
        )
    except Exception:
        degraded = True

    milvus_count = len(m_hits)
    es_count = len(e_hits)
    after_dedup = len({h.chunk_id for h in list(m_hits) + list(e_hits)})
    routing = (
        "both" if milvus_count > 0 and es_count > 0
        else "milvus_only" if milvus_count > 0
        else "es_only" if es_count > 0
        else "none"
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "retrieval", elapsed_ms=elapsed_ms,
        milvus_hits=milvus_count, es_hits=es_count,
        after_dedup=after_dedup, routing=routing, degraded=degraded,
    )
    await emit_step("retrieval", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "hits": m_hits,
        "es_hits": e_hits,
        "rag_steps": {**state.get("rag_steps", {}), "retrieval": step},
    }
