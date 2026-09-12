"""
LLM 回答生成 — reranked hits → 拼 context → DeepSeek-V4-Pro → 回答

用法:
    from app.infrastructure.adapters.llm_answer import answer, answer_stream

    result = answer("高血压怎么用药", reranked_hits)
    for token in answer_stream("高血压怎么用药", reranked_hits):
        print(token, end="")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Generator

from langchain_core.messages import HumanMessage, SystemMessage

from app.domain.knowledge_base import KBKind
from app.domain.rag.prompts import CONTEXT_TEMPLATE, GENERIC_SYSTEM_PROMPT, SYSTEM_PROMPT
from app.infrastructure.settings import get_settings
from app.interface.deps import get_container

logger = logging.getLogger("llm_answer")


def _chat_model(streaming: bool):
    """经容器取 DeepSeek 回答模型（模型名读 Settings 单一真相源）。"""
    return get_container().get_llm().get_chat_model(
        model=get_settings().deepseek_answer_model,
        temperature=0.3,
        streaming=streaming,
    )


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
        if len(content) > 800:
            content = content[:800] + "..."

        if h.title_cn or h.journal:
            lines.append(
                f"[{count}] 标题: 《{h.title_cn or ''}》"
                f" | 来源: {h.journal or '中国全科医学'}"
                f"{heading_part}\n"
                f"    内容: {content}"
            )
        else:
            lines.append(
                f"[{count}] {h.title or '未知文档'}"
                f"{heading_part}\n"
                f"    内容: {content}"
            )

    return "\n\n".join(lines)


@dataclass
class AnswerResult:
    answer: str = ""
    sources: list = field(default_factory=list)
    intent: object | None = None


def build_answer_prompt(
    query: str,
    hits: list,
    history: list[dict] | None = None,
    top_n: int = 5,
) -> str:
    """构建 LLM user_prompt（context + history_block + query）。

    context 由 `format_context` 拼装；history 取最近 20 条（10 turns）。
    """
    context = format_context(hits, top_n=top_n)

    history_block = ""
    if history:
        lines = ["## 对话历史\n"]
        for m in history[-20:]:
            role_label = "用户" if m["role"] == "user" else "AI"
            lines.append(f"{role_label}：{m['content']}")
        lines.append("")
        history_block = "\n".join(lines) + "\n"

    return CONTEXT_TEMPLATE.format(
        history_block=history_block,
        context=context,
        query=query,
    )


def answer(
    query: str,
    hits: list,
    history: list[dict] | None = None,
    intent: object | None = None,
    top_n: int = 5,
    stream: bool = False,
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
) -> AnswerResult | Generator[str, None, None]:
    """
    根据检索结果生成 LLM 回答。

    参数:
        query: 用户原始查询
        hits: rerank 后的 SearchHit 列表
        history: 对话历史 [{"role":"user"|"ai","content":"..."}] 最近 N 条
        intent: 意图识别结果 (可选)
        top_n: 取前 N 条有 content 的 hit 拼 context
        stream: 是否流式输出
        kb_kind: 知识库类型（MEDICAL_DEFAULT→期刊 prompt；GENERIC→通用 prompt）

    返回:
        stream=False → AnswerResult
        stream=True  → Generator[str, None, None]
    """
    context = format_context(hits, top_n=top_n)
    if not context:
        return AnswerResult(answer="未找到相关文献信息，无法回答。", sources=[], intent=intent)

    user_prompt = build_answer_prompt(query, hits, history, top_n=top_n)

    if stream:
        return _answer_stream(user_prompt, hits, intent, kb_kind)

    return _answer_sync(user_prompt, hits, intent, kb_kind)


def _answer_sync(
    user_prompt: str,
    hits: list,
    intent: object | None = None,
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
) -> AnswerResult:
    """非流式：等待完整回答后返回"""
    sys_prompt = GENERIC_SYSTEM_PROMPT if kb_kind is KBKind.GENERIC else SYSTEM_PROMPT
    try:
        chat = _chat_model(streaming=False)
        resp = chat.invoke([
            SystemMessage(content=sys_prompt),
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
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
) -> Generator[str, None, None]:
    """流式：逐 token yield"""
    sys_prompt = GENERIC_SYSTEM_PROMPT if kb_kind is KBKind.GENERIC else SYSTEM_PROMPT
    try:
        chat = _chat_model(streaming=True)
        stream = chat.stream([
            SystemMessage(content=sys_prompt),
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
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
) -> Generator[str, None, None]:
    """流式回答的快捷入口，等价于 answer(..., stream=True)"""
    return answer(query, hits, intent, top_n=top_n, stream=True, kb_kind=kb_kind)


async def answer_stream_async(
    user_prompt: str,
    kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
):
    """流式回答（async）→ 逐 token yield；**LLM 异常上抛**（不产 `[错误:...]`）。 供 QAGraph answer 节点用（C8：async 图 + async LLM 流式，不阻塞 event loop）。
    失败交给 error_handler 产 `t:error`，而非把错误拼进正文（A-4.4 修复）。
    """
    sys_prompt = GENERIC_SYSTEM_PROMPT if kb_kind is KBKind.GENERIC else SYSTEM_PROMPT
    chat = _chat_model(streaming=True)
    stream = chat.astream([
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_prompt),
    ])
    async for chunk in stream:
        content = getattr(chunk, "content", "")
        if content:
            yield content
