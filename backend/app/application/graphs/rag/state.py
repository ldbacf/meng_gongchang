"""QAGraph 状态契约（总需求 §6.3 / §4.2.1 落地）。

- message 级线程：`thread_id = rag:{conversation_id}:{message_id}`（D3）。
- token 级流式内容**不进 state**（answer 节点只写结果，不写逐 token），
  避免高频序列化（C6 方案①）；token 经 `adispatch_custom_event('token', ...)` 出图。
- `rag_steps`：每步 `{status, title, elapsed_ms, metrics}`（`build_rag_step` 单工厂）。
"""
from __future__ import annotations

from typing import TypedDict


class QaState(TypedDict, total=False):
    # 运行标识
    message_id: str
    conversation_id: str
    user_id: str
    query: str
    kb: dict  # {kb_id, es_index, milvus_collection, kb_kind}
    history: list  # [{role, content}] 回答 10 turns / 意图 2 turns
    # 处理中间态
    rewritten_query: str
    expanded_query: str | None
    intent: dict  # {name, confidence, coverage, degraded}
    hits: list | None  # [SearchHit] 初召 milvus 路（未融合）
    es_hits: list | None  # [SearchHit] 初召 es 路（fusion 节点与 hits 一并 rrf）
    reranked: list | None  # [SearchHit] 融合重排后
    citations: list | None  # [{idx, doc_id, title, snippet, md5}]
    # 结果 / 终态
    answer: str | None
    rag_steps: dict  # 每步 {status, title, elapsed_ms, metrics}
    error: dict | None  # {step, kind, message, retryable}
    done: bool
