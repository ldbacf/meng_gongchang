"""intent — 意图识别 + 指代消解 + （可选）查询扩展。

- `analyze_intent(query, last_context, kb_kind)`：Medical/Generic 策略（domain 纯函数）。
- 失败 → 降级（`degraded=True`），`rewritten_query` 回退原 query（A-4.5，不中断）。
- `USE_QUERY_EXPANSION=true` 时再经 `expand_query` 追加专业术语（条件节点，折叠于此）。
"""
from __future__ import annotations

import asyncio
import time

from app.application.graphs.rag.nodes._common import last_context_from_history
from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step
from app.domain.knowledge_base import KBKind
from app.domain.rag.intent import IntentResult
from app.interface.deps import get_container


async def intent(state: dict) -> dict:
    query = state["query"]
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))
    last_context = last_context_from_history(state.get("history") or [])

    from src.query_intent import analyze_intent

    t0 = time.perf_counter()
    await emit_step("intent", "pending")

    result = None
    degraded = False
    try:
        result = await asyncio.to_thread(analyze_intent, query, last_context, kb_kind)
        # API 失败时 analyze_intent 返回 fallback（domain/coverage 为空）→ 判定降级
        degraded = not (bool(result.domain) or bool(result.coverage))
    except Exception:
        degraded = True

    sr = result or IntentResult()
    rewritten = sr.rewritten_query or query

    expanded_query = None
    if get_container().get_settings().use_query_expansion:
        from src.query_expansion import expand_query

        exp = await asyncio.to_thread(expand_query, query)
        if exp and exp != query:
            expanded_query = exp
            rewritten = f"{rewritten} {exp}"

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "intent", elapsed_ms=elapsed_ms,
        domain=sr.domain, coverage=sr.coverage, rewritten_query=rewritten,
        keywords=sr.keywords, suggestion=sr.suggestion, degraded=degraded,
    )
    await emit_step("intent", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "intent": {
            "name": sr.domain or "通用",
            "confidence": sr.coverage or "unknown",
            "coverage": sr.coverage or "unknown",
            "degraded": degraded,
        },
        "rewritten_query": rewritten,
        "expanded_query": expanded_query,
        "rag_steps": {**state.get("rag_steps", {}), "intent": step},
    }
