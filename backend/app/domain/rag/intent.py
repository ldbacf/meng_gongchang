"""查询意图策略 — Medical（期刊）/ Generic（通用文档）两实现（纯函数资产）。

LLM 调用（`get_chat_model`）留在 `src/query_intent.py` 适配层；本模块只持有
策略（prompt 选择）与响应解析（`parse_intent_response`）。零外部依赖。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.domain.knowledge_base import KBKind
from app.domain.rag.prompts import INTENT_GENERIC_PROMPT, INTENT_SYSTEM_PROMPT


@dataclass
class IntentResult:
    domain: str = ""
    coverage: str = ""  # high / medium / low / out_of_domain
    rewritten_query: str = ""
    keywords: list[str] = field(default_factory=list)
    suggestion: str = ""


class QueryIntentStrategy:
    """意图策略基类：选择 system prompt + 解析响应。"""

    system_prompt: str = ""

    @classmethod
    def parse(cls, text: str) -> IntentResult:
        return parse_intent_response(text)


class MedicalIntentStrategy(QueryIntentStrategy):
    system_prompt = INTENT_SYSTEM_PROMPT


class GenericIntentStrategy(QueryIntentStrategy):
    system_prompt = INTENT_GENERIC_PROMPT


def get_intent_strategy(kb_kind: KBKind) -> QueryIntentStrategy:
    return GenericIntentStrategy() if kb_kind is KBKind.GENERIC else MedicalIntentStrategy()


def parse_intent_response(text: str) -> IntentResult:
    """解析 LLM 返回的 JSON → IntentResult；解析失败返回空结果。"""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return IntentResult()
    return IntentResult(
        domain=obj.get("domain", ""),
        coverage=obj.get("coverage", ""),
        rewritten_query=obj.get("rewritten_query", ""),
        keywords=obj.get("keywords", []),
        suggestion=obj.get("suggestion", ""),
    )
