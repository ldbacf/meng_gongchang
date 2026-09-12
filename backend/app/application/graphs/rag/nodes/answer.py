"""answer — DeepSeek 流式回答。

- `build_answer_prompt`（context + history_block）→ `answer_stream_async`（async LLM 流式）。
- token 逐条 `adispatch_custom_event('token', {'c':...})` → SSE `t:text`（C7，不进 state）。
- token 级内容**不写入 state**（C6 方案①，避免高频序列化）；仅整段 `answer` 在节点末写入。
- LLM 流失败 → 直接上抛（不产 `[错误:...]`，交 service error_handler 产 `t:error`）；
  断连续跑由 checkpoint resume 从本段重放（A-4.3），不做节点内重试（防 token 重复）。
- 文献不足（reranked 无 content）→ 直接给"未找到"占位，不调 LLM。
"""
from __future__ import annotations

import time

from app.application.graphs.rag.nodes._emit import emit_step, emit_text
from app.application.rag.rag_metrics import build_rag_step
from app.domain.knowledge_base import KBKind


async def answer(state: dict) -> dict:
    from src.llm_answer import answer_stream_async, build_answer_prompt

    query = state["query"]
    reranked = state.get("reranked") or []
    history = state.get("history") or []
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))

    t0 = time.perf_counter()
    await emit_step("answer", "pending")

    has_content = any(getattr(h, "content", "") for h in reranked)
    full: list[str] = []
    if not has_content:
        full = ["未找到相关文献信息，无法回答。"]
    else:
        from app.infrastructure.observability.instrument import tracked_span

        from app.interface.deps import get_container

        user_prompt = build_answer_prompt(query, reranked, history, top_n=5)
        # 单次流式；失败上抛（服务层 error_handler 产 t:error + 落库 failed）
        m = get_container().get_metrics()
        with tracked_span(
            "answer.llm",
            latency_metric=m.llm_latency,
            error_metric=m.llm_error_total,
        ):
            async for tok in answer_stream_async(user_prompt, kb_kind):
                full.append(tok)
                await emit_text(tok)

    answer_text = "".join(full)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "answer", elapsed_ms=elapsed_ms,
        context_chunks=min(5, len(reranked)),
        total_tokens=len(answer_text),
        total_elapsed_ms=elapsed_ms,
        degraded=False,
    )
    await emit_step("answer", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "answer": answer_text,
        "rag_steps": {**state.get("rag_steps", {}), "answer": step},
    }
