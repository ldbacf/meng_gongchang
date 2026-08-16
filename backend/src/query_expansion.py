"""
查询术语扩展模块 — 适配层（LLM 调用），prompt/解析在 `app/domain/rag/query_expansion.py`。

用法:
    from src.query_expansion import expand_query

    expanded = expand_query("一天吃七八种药会不会互相影响")
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.domain.rag.prompts import EXPANSION_SYSTEM_PROMPT
from app.domain.rag.query_expansion import parse_expansion_response
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_INTENT_MODEL

logger = logging.getLogger("query_expansion")


def expand_query(query: str, timeout: float = 8.0) -> str:
    """
    将口语化医疗查询扩展为专业检索关键词。

    返回:
        str: 扩展后的专业检索词（空格分隔），失败时返回原 query
    """
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("your-"):
        return query

    from src.llm import get_chat_model

    chat = get_chat_model(model=DEEPSEEK_INTENT_MODEL, temperature=0.0)

    try:
        resp = chat.bind(response_format={"type": "json_object"}).invoke(
            [
                SystemMessage(content=EXPANSION_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ],
        )
    except Exception as e:
        logger.warning("DeepSeek API 调用失败: %s", e)
        return query

    expanded = parse_expansion_response(resp.content)
    return expanded if expanded else query
