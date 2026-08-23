"""fusion — RRF 融合 + Rerank（Qwen3-Reranker-4B）。

- `rrf_fusion(hits, es_hits, k=20)` 按 chunk_id 去重 + ES 富字段回填（domain 纯函数）。
- rerank 失败（抛错或静默全 0 分）→ **保序返回 + `degraded=True`**（不中断，A-4.5）。
"""
from __future__ import annotations

import asyncio
import time

from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step
from app.domain.retrieval.rrf import rrf_fusion


async def _rerank(query: str, hits: list):
    from src.search import rerank

    return await asyncio.to_thread(rerank, query, hits, 5)


async def fusion(state: dict) -> dict:
    query = state["query"]
    m_hits = state.get("hits") or []
    e_hits = state.get("es_hits") or []

    t0 = time.perf_counter()
    await emit_step("fusion", "pending")

    fused = rrf_fusion(m_hits, e_hits, k=20, top_k=100)

    degraded = False
    reranked = list(fused)
    try:
        reranked = await _rerank(query, fused)
        # 静默失败信号：有 hits 但重排后无一条正分 → 判降级（rerank 内部吞异常不抛）
        if fused and all(getattr(h, "score_rerank", 0) <= 0 for h in reranked):
            degraded = True
    except Exception:
        reranked = list(fused)
        degraded = True

    top_scores = [round(h.score_rerank, 3) for h in reranked[:5] if h.score_rerank > 0]

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "fusion", elapsed_ms=elapsed_ms,
        input_count=len(fused), output_count=len(reranked),
        top_scores=top_scores, degraded=degraded,
    )
    await emit_step("fusion", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "hits": fused,
        "reranked": reranked,
        "rag_steps": {**state.get("rag_steps", {}), "fusion": step},
    }
