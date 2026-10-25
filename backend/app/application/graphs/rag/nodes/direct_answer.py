"""direct_answer — 不检索、直接回答（意图判定为库外 / 寒暄）。

## 何时走这里
`domain.rag.routing.decide_route()` 判定 `coverage == out_of_domain` 时，
`intent` 之后的条件边跳过 `retrieval → fusion → cite`，直接进入本节点。

## 与 `answer` 节点的区别
- 没有 `reranked` 上下文 → 用 `DIRECT_SYSTEM_PROMPT` 覆盖"只用文献回答"的约束，
  否则模型会照着默认提示词说"信息不足"
- 产出 `citations = []`，前端不会出现引用列表
- `rag_steps` 只有 intent + answer 两步（前端按存在与否渲染，自然只显示 2 步）
- answer 步的 metrics 带 `route: "direct"`，便于统计"多少提问根本没走检索"

## 失败语义
与 `answer` 一致：LLM 流失败直接上抛，由 service 层产 `t:error` 并落库 failed。
"""
from __future__ import annotations

import time

from app.application.graphs.rag.nodes._emit import emit_step, emit_text
from app.application.rag.rag_metrics import build_rag_step
from app.domain.knowledge_base import KBKind
from app.domain.rag.prompts import DIRECT_SYSTEM_PROMPT, DIRECT_USER_TEMPLATE


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["## 对话历史\n"]
    for m in history[-20:]:
        role = "用户" if m.get("role") == "user" else "AI"
        lines.append(f"{role}：{m.get('content', '')}")
    return "\n".join(lines) + "\n\n"


async def direct_answer(state: dict) -> dict:
    from app.infrastructure.adapters.ports_impl import get_generation_adapter
    from app.infrastructure.container import get_container
    from app.infrastructure.observability.instrument import tracked_span

    gen = get_generation_adapter()
    query = state["query"]
    history = state.get("history") or []
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))
    intent = state.get("intent") or {}

    t0 = time.perf_counter()
    await emit_step("answer", "pending")

    user_prompt = DIRECT_USER_TEMPLATE.format(
        history_block=_history_block(history),
        query=query,
    )

    full: list[str] = []
    m = get_container().get_metrics()
    with tracked_span(
        "answer.direct",
        latency_metric=m.llm_latency,
        error_metric=m.llm_error_total,
    ):
        async for tok in gen.stream(
            user_prompt, kb_kind, system_prompt=DIRECT_SYSTEM_PROMPT
        ):
            full.append(tok)
            await emit_text(tok)

    answer_text = "".join(full)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "answer", elapsed_ms=elapsed_ms,
        context_chunks=0,
        total_tokens=len(answer_text),
        total_elapsed_ms=elapsed_ms,
        route="direct",
    )
    await emit_step("answer", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "answer": answer_text,
        # 直答不产生引用，显式置空（前端据此不渲染参考文献区）
        "citations": [],
        "reranked": [],
        "intent": intent,
        "rag_steps": {**state.get("rag_steps", {}), "answer": step},
    }
