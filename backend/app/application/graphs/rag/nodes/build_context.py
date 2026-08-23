"""build_context — 历史窗口 + KB 目标解析（QAGraph 首节点）。

- `history` 裁剪为最近 20 条（回答用 10 turns），供 answer prompt 用。
- `kb` 归一化（补齐 kb_kind 缺省），供下游 KBKind 策略分支。
"""
from __future__ import annotations


async def build_context(state: dict) -> dict:
    history = state.get("history") or []
    trimmed = history[-20:]  # 10 turns

    kb = dict(state.get("kb") or {})
    if not kb.get("kb_kind"):
        kb["kb_kind"] = "medical_default"  # 缺省期刊策略（未解析到 KB 时兜底）

    return {"history": trimmed, "kb": kb}
