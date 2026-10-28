"""fusion — RRF 融合 + Rerank（Qwen3-Reranker-4B）。

- `rrf_fusion(hits, es_hits, k=20)` 按 chunk_id 去重 + ES 富字段回填（domain 纯函数）。
- rerank 失败（抛错或静默全 0 分）→ **保序返回 + `degraded=True`**（不中断，A-4.5）。

rerank 经 `domain.ports.retrieval.RetrievalPort`（adapters.ports_impl 实现），
不直接 import 具体检索模块。
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step, describe_exception
from app.domain.retrieval.rrf import rrf_fusion

logger = logging.getLogger(__name__)


async def _rerank(query: str, hits: list):
    from app.infrastructure.adapters.ports_impl import get_search_adapter

    return await asyncio.to_thread(get_search_adapter().rerank, query, hits, 5)


async def fusion(state: dict) -> dict:
    query = state["query"]
    m_hits = state.get("hits") or []
    e_hits = state.get("es_hits") or []

    t0 = time.perf_counter()
    await emit_step("fusion", "pending")

    fused = rrf_fusion(m_hits, e_hits, k=20, top_k=100)

    # ── 实时计数（真实值，不是估算） ──
    #
    # 两个点天然可得：rrf 去重后的候选数、rerank 之后的精选数。
    # 中间那段 rerank 是**阻塞调用**（一次 HTTP 往返），没有可上报的中间量，
    # 所以这里只能给出「比对 12 篇」→「精选 5 段」两次跳变，不伪造递增。
    if fused:
        await emit_step("fusion", "pending", metrics={
            "live": True,
            "stage": "rerank",
            "input_count": len(fused),
            "output_count": 0,
        })

    degraded = False
    degraded_reason = ""
    degraded_exc: BaseException | None = None
    reranked = list(fused)
    try:
        reranked = await _rerank(query, fused)
        # 静默失败信号：有 hits 但重排后无一条正分 → 判降级（rerank 内部吞异常不抛）
        if fused and all(getattr(h, "score_rerank", 0) <= 0 for h in reranked):
            degraded = True
            degraded_reason = "重排全部返回 0 分（服务可能未生效或额度耗尽）"
    except Exception as exc:
        reranked = list(fused)
        degraded, degraded_exc = True, exc

    # 降级留痕：与 retrieval 同理 —— 静默降级时排序退化成 RRF 顺序，
    # 答案质量下降却没有任何信号，排查时无从下手。
    if degraded:
        if degraded_exc is not None:
            degraded_reason = describe_exception(degraded_exc)
        logger.warning(
            "重排降级，保序返回 RRF 结果: %s",
            degraded_reason,
            exc_info=degraded_exc,
            extra={"ctx": {"query": query, "input_count": len(fused)}},
        )

    top_scores = [round(h.score_rerank, 3) for h in reranked[:5] if h.score_rerank > 0]

    # 精选数出来了再报一次（前端「精选 5 段」）
    if reranked:
        await emit_step("fusion", "pending", metrics={
            "live": True,
            "stage": "rerank",
            "input_count": len(fused),
            "output_count": len(reranked),
        })

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "fusion", elapsed_ms=elapsed_ms,
        input_count=len(fused), output_count=len(reranked),
        top_scores=top_scores, degraded=degraded,
        degraded_reason=degraded_reason,
    )
    await emit_step("fusion", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "hits": fused,
        "reranked": reranked,
        "rag_steps": {**state.get("rag_steps", {}), "fusion": step},
    }
