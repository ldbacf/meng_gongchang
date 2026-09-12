"""
查询意图识别模块 — 适配层（LLM 调用），策略/prompt/解析在 `app/domain/rag/intent.py`。

用法:
    from src.query_intent import analyze_intent

    intent = await asyncio.to_thread(analyze_intent, "儿童发热怎么用药")
    print(intent.coverage)         # low
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.domain.knowledge_base import KBKind
from app.domain.rag.intent import (  # noqa: F401  re-export
    IntentResult,
    get_intent_strategy,
    parse_intent_response,
)
from app.infrastructure.settings import get_settings

logger = logging.getLogger("query_intent")


def analyze_intent(
    query: str,
    last_context: str = "",
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
    timeout: float = 10.0,
) -> IntentResult:
    """
    分析用户查询意图，返回分类结果和重写后的 query。

    参数:
        query: 用户原始查询
        last_context: 最近对话上下文（用于指代消解）
        kb_kind: 知识库类型（MEDICAL_DEFAULT→期刊 prompt；GENERIC→通用 prompt）
        timeout: API 超时秒数

    返回:
        IntentResult，失败时返回原 query 直通的默认结果
    """
    from app.interface.deps import get_container

    s = get_settings()
    if not s.deepseek_api_key or s.deepseek_api_key.startswith("your-"):
        return IntentResult(rewritten_query=query)

    chat = get_container().get_llm().get_chat_model(
        model=s.deepseek_intent_model, temperature=0.0,
    )

    strategy = get_intent_strategy(kb_kind)

    user_message = query
    if last_context:
        user_message = f"上轮对话：\n{last_context}\n\n当前提问：{query}\n\n请根据上轮对话，将当前提问中可能存在的指代词（如\"它\"\"这个\"\"上面\"）替换为具体内容，重写为独立的检索查询。"

    from app.infrastructure.observability.instrument import tracked_span

    try:
        with tracked_span(
            "intent.llm",
            latency_metric=get_container().get_metrics().llm_latency,
            error_metric=get_container().get_metrics().llm_error_total,
        ):
            resp = chat.bind(response_format={"type": "json_object"}).invoke(
                [
                    SystemMessage(content=strategy.system_prompt),
                    HumanMessage(content=user_message),
                ],
            )
    except Exception as e:
        logger.warning("DeepSeek API 调用失败: %s", e)
        return IntentResult(rewritten_query=query)

    result = parse_intent_response(resp.content)
    if not result.rewritten_query:
        result.rewritten_query = query
    return result
