"""
LLM 回答生成 — reranked hits → 拼 context → DeepSeek-V4-Pro → 回答

用法:
    from src.llm_answer import answer, answer_stream

    # 非流式
    result = answer("高血压怎么用药", reranked_hits, intent)
    print(result.answer)

    # 流式
    for token in answer_stream("高血压怎么用药", reranked_hits):
        print(token, end="")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Generator

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import DEEPSEEK_ANSWER_MODEL
from src.llm import get_chat_model

logger = logging.getLogger("llm_answer")

# ═══════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个医学文献分析助手，基于提供的文献片段回答用户问题。

规则：
1. 只使用提供的文献信息回答，不编造内容
2. 如果提供的文献信息不足以回答问题，明确说明"当前文献未涉及"或"信息不足"
3. 引用来源用 [序号] 标注，例如"根据研究[1]显示..."
4. 使用中文回答，专业简洁
5. 综合多个文献片段的信息给出完整回答
6. 如果用户使用了指代词（如"它""这个""上面"），请结合对话历史理解用户真实意图"""  # noqa: E501

CONTEXT_TEMPLATE = """{history_block}以下是相关文献片段：

{context}

请基于以上文献回答：{query}"""


def format_context(
    hits: list,
    top_n: int = 5,
) -> str:
    """
    将 reranked hits 拼装为 prompt 中的 context 文本。

    每个片段格式:
    [N] 标题: 《xxx》 | 来源: 中国全科医学 | 章节: heading_stack
        内容: xxx

    只取 top_n 条有 content 的 hit。
    """
    lines = []
    count = 0
    for h in hits:
        if not h.content:
            continue
        count += 1
        if count > top_n:
            break

        heading = " → ".join(h.heading_stack) if h.heading_stack else ""
        heading_part = f" | 章节: {heading}" if heading else ""
        content = h.content.strip().replace("\n", " ")
        # 截断超长内容防止 prompt 过长
        if len(content) > 800:
            content = content[:800] + "..."

        lines.append(
            f"[{count}] 标题: 《{h.title_cn or ''}》"
            f" | 来源: 中国全科医学"
            f"{heading_part}\n"
            f"    内容: {content}"
        )

    return "\n\n".join(lines)


@dataclass
class AnswerResult:
    answer: str = ""
    sources: list = field(default_factory=list)
    intent: object | None = None


def answer(
    query: str,
    hits: list,
    history: list[dict] | None = None,
    intent: object | None = None,
    top_n: int = 5,
    stream: bool = False,
) -> AnswerResult | Generator[str, None, None]:
    """
    根据检索结果生成 LLM 回答。

    参数:
        query: 用户原始查询
        hits: rerank 后的 SearchHit 列表
        history: 对话历史 [{"role":"user"|"ai","content":"..."}] 最近 N 条
        intent: 意图识别结果 (可选，用于信息展示)
        top_n: 取前 N 条有 content 的 hit 拼 context
        stream: 是否流式输出

    返回:
        stream=False → AnswerResult
        stream=True  → Generator[str, None, None] (逐 token yield)
    """
    context = format_context(hits, top_n=top_n)
    if not context:
        return AnswerResult(answer="未找到相关文献信息，无法回答。", sources=[], intent=intent)

    # Build history block
    history_block = ""
    if history:
        lines = ["## 对话历史\n"]
        for m in history[-20:]:
            role_label = "用户" if m["role"] == "user" else "AI"
            lines.append(f"{role_label}：{m['content']}")
        lines.append("")
        history_block = "\n".join(lines) + "\n"

    user_prompt = CONTEXT_TEMPLATE.format(
        history_block=history_block,
        context=context,
        query=query,
    )

    if stream:
        return _answer_stream(user_prompt, hits, intent)

    return _answer_sync(user_prompt, hits, intent)


def _answer_sync(
    user_prompt: str,
    hits: list,
    intent: object | None = None,
) -> AnswerResult:
    """非流式：等待完整回答后返回"""
    try:
        chat = get_chat_model(model=DEEPSEEK_ANSWER_MODEL, temperature=0.3, streaming=False)
        resp = chat.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        return AnswerResult(answer=resp.content.strip(), sources=hits, intent=intent)
    except Exception as e:
        logger.error("LLM 回答生成失败: %s", e)
        return AnswerResult(answer=f"回答生成失败: {e}", sources=hits, intent=intent)


def _answer_stream(
    user_prompt: str,
    hits: list,
    intent: object | None = None,
) -> Generator[str, None, None]:
    """流式：逐 token yield"""
    try:
        chat = get_chat_model(model=DEEPSEEK_ANSWER_MODEL, temperature=0.3, streaming=True)
        stream = chat.stream([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        for chunk in stream:
            content = chunk.content
            if content:
                yield content
    except Exception as e:
        logger.error("LLM 流式回答失败: %s", e)
        yield f"[错误: {e}]"


def answer_stream(
    query: str,
    hits: list,
    intent: object | None = None,
    top_n: int = 5,
) -> Generator[str, None, None]:
    """流式回答的快捷入口，等价于 answer(..., stream=True)"""
    return answer(query, hits, intent, top_n=top_n, stream=True)
