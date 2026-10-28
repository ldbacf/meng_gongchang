"""intent — 意图识别 + 指代消解 + （可选）查询扩展。

- `analyze_intent(query, last_context, kb_kind)`：Medical/Generic 策略（domain 纯函数）。
- 失败 → 降级（`degraded=True`），`rewritten_query` 回退原 query（A-4.5，不中断）。
- `USE_QUERY_EXPANSION=true` 时再经 `expand_query` 追加专业术语（条件节点，折叠于此）。

意图 / 扩展经 `domain.ports.generation`（adapters.ports_impl 实现），
不直接 import 具体适配器模块。
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.application.graphs.rag.nodes._common import last_context_from_history
from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step, describe_exception
from app.domain.knowledge_base import KBKind
from app.domain.rag.intent import IntentResult
from app.infrastructure.adapters.ports_impl import get_generation_adapter
from app.infrastructure.container import get_container

logger = logging.getLogger(__name__)


async def intent(state: dict) -> dict:
    query = state["query"]
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))
    last_context = last_context_from_history(state.get("history") or [])

    gen = get_generation_adapter()

    t0 = time.perf_counter()
    await emit_step("intent", "pending")

    result = None
    degraded = False
    degraded_reason = ""
    degraded_exc: BaseException | None = None
    try:
        result = await asyncio.to_thread(gen.analyze, query, last_context, kb_kind)
        # API 失败时 analyze 返回 fallback（domain/coverage 为空）→ 判定降级
        if not (bool(result.domain) or bool(result.coverage)):
            degraded = True
            degraded_reason = "意图模型返回空结果（domain / coverage 均为空）"
    except Exception as exc:
        degraded, degraded_exc = True, exc

    # 降级留痕：意图降级会让 coverage 变 unknown → 一律走检索（保守），
    # 行为是对的，但用户与日志都看不到"这一步其实失败了"。
    if degraded:
        if degraded_exc is not None:
            degraded_reason = describe_exception(degraded_exc)
        logger.warning(
            "意图识别降级，按 coverage=unknown 继续检索: %s",
            degraded_reason,
            exc_info=degraded_exc,
            extra={"ctx": {"query": query, "kb_kind": kb_kind.value}},
        )

    sr = result or IntentResult()
    rewritten = sr.rewritten_query or query

    expanded_query = None
    if get_container().get_settings().use_query_expansion:
        exp = await asyncio.to_thread(gen.expand, query)
        if exp and exp != query:
            expanded_query = exp
            rewritten = f"{rewritten} {exp}"

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "intent", elapsed_ms=elapsed_ms,
        domain=sr.domain, coverage=sr.coverage, rewritten_query=rewritten,
        keywords=sr.keywords, suggestion=sr.suggestion, degraded=degraded,
        degraded_reason=degraded_reason,
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
