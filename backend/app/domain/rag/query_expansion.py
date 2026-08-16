"""查询术语扩展 — prompt 资产 + 响应解析（纯函数）。

LLM 调用留在 `src/query_expansion.py` 适配层；本模块持有 prompt 与 `parse_expansion_response`。
"""
from __future__ import annotations

import json

from app.domain.rag.prompts import EXPANSION_SYSTEM_PROMPT


def parse_expansion_response(text: str) -> str:
    """解析 LLM 返回的 JSON → 扩展后关键词串；失败返回空串。"""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return ""
    return obj.get("expanded_query", "").strip()
