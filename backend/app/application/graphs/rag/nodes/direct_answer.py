"""direct_answer — 不检索 / 证据不足时直接回答。

## 两种进入方式

| 来源 | 触发条件 | 原因标记 |
|---|---|---|
| `intent` 之后 | 意图判定 `coverage == out_of_domain`（寒暄 / 元问题 / 完全库外） | `out_of_domain` |
| `fusion` 之后 | 检索跑完但**证据不够**：无正文片段，或 rerank top1 低于阈值 | `no_content` / `low_evidence` |

两种原因用**不同的系统提示词**：
- `out_of_domain` → `DIRECT_SYSTEM_PROMPT`（别谈文献，正常聊天 / 答常识）
- `low_evidence` / `no_content` → `LOW_EVIDENCE_SYSTEM_PROMPT`
  （先说明"库内无相关文献"，再给通用参考，明确禁止编造引用）

## 为什么还要服务端追加声明
提示词是"请求模型照做"，不是"保证"。所以在流式结束后**额外补一句固定声明**，
确保用户一定看到"这段不是库里的证据"，而不是赌模型听话。
声明经 `emit_text` 发出，因此也会进入前端已揭示文本与落库内容。

## 失败语义
与 `answer` 一致：LLM 流失败直接上抛，由 service 层产 `t:error` 并落库 failed。
"""
from __future__ import annotations

import time

from app.application.graphs.rag.nodes._emit import emit_step, emit_text
from app.application.rag.rag_metrics import build_rag_step
from app.domain.knowledge_base import KBKind
from app.domain.rag.prompts import (
    DIRECT_SYSTEM_PROMPT,
    DIRECT_USER_TEMPLATE,
    LOW_EVIDENCE_SYSTEM_PROMPT,
)

#: 服务端强制追加的声明（按原因区分）
DISCLAIMERS = {
    "out_of_domain": "",
    "low_evidence": (
        "\n\n> 说明：知识库中未检索到与该问题相关的可靠文献，"
        "以上内容为通用知识参考，**未引用本知识库文献**。"
    ),
    "no_content": (
        "\n\n> 说明：知识库中未检索到可用的文献片段，"
        "以上内容为通用知识参考，**未引用本知识库文献**。"
    ),
}


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["## 对话历史\n"]
    for m in history[-20:]:
        role = "用户" if m.get("role") == "user" else "AI"
        lines.append(f"{role}：{m.get('content', '')}")
    return "\n".join(lines) + "\n\n"


def resolve_reason(state: dict) -> str:
    """从 state 推断为什么走直答（条件边不能改 state，只能在这里读）。

    判据是「**有没有跑过 retrieval 这一步**」——按 key 是否存在判断，
    不能按 step 字典是否为空判断（空 dict 是 falsy，会误判成"没检索"）。
    """
    steps = state.get("rag_steps") or {}
    if "retrieval" not in steps:
        return "out_of_domain"

    reranked = state.get("reranked") or []
    if not any(getattr(h, "content", "") for h in reranked):
        return "no_content"
    return "low_evidence"


async def direct_answer(state: dict) -> dict:
    from app.infrastructure.adapters.ports_impl import get_generation_adapter
    from app.infrastructure.container import get_container
    from app.infrastructure.observability.instrument import tracked_span

    gen = get_generation_adapter()
    query = state["query"]
    history = state.get("history") or []
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))

    reason = resolve_reason(state)
    system_prompt = (
        DIRECT_SYSTEM_PROMPT if reason == "out_of_domain" else LOW_EVIDENCE_SYSTEM_PROMPT
    )

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
        async for tok in gen.stream(user_prompt, kb_kind, system_prompt=system_prompt):
            full.append(tok)
            await emit_text(tok)

    # 确定性声明：不依赖模型是否照做
    disclaimer = DISCLAIMERS.get(reason, "")
    if disclaimer:
        full.append(disclaimer)
        await emit_text(disclaimer)

    answer_text = "".join(full)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "answer", elapsed_ms=elapsed_ms,
        context_chunks=0,
        total_tokens=len(answer_text),
        total_elapsed_ms=elapsed_ms,
        route=reason,
    )
    await emit_step("answer", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "answer": answer_text,
        # 直答不产生引用，显式置空（前端据此不渲染参考文献区）
        "citations": [],
        "rag_steps": {**state.get("rag_steps", {}), "answer": step},
    }
