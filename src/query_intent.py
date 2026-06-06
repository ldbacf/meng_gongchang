"""
查询意图识别模块 — DeepSeek-V4-Flash 分析 query → 领域分类 + 覆盖度 + 重写

用法:
    from src.query_intent import analyze_intent

    intent = analyze_intent("儿童发热怎么用药")
    print(intent.coverage)         # low
    print(intent.rewritten_query)  # 儿童发热 药物治疗 儿科用药安全
    print(intent.suggestion)       # 当前语料库以全科医学为主，儿科临床指南覆盖较少...
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_INTENT_MODEL

logger = logging.getLogger("query_intent")

# ═══════════════════════════════════════════════════════════════
# System Prompt — 语料覆盖地图 + 任务指令
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是医学文献检索的查询重写助手。你的任务是判断 query 覆盖领域并重写为检索友好的形式。

## 语料覆盖地图
当前语料库为《中国全科医学》期刊的 1248 篇论文：
- 高覆盖：高血压、糖尿病、心血管疾病、慢性病管理、全科医学/基层医疗、临床指南、Meta分析、脑卒中
- 中等覆盖：老年人健康、中医药、呼吸系统、慢性肾病、精神心理
- 低覆盖：儿科、肿瘤、消化、妇产科
- 无覆盖：外科手术、急诊急救、罕见病、基础医学

## 任务
1. 判断用户 query 的领域和覆盖度：high / medium / low / out_of_domain
2. 将 query 重写为检索友好的形式，遵守以下规则：
   a) 保留用户原始 query 的所有核心关键词，禁止删除或替换
   b) 如果 query 已是简洁关键词形式（不超过 15 个字），直接原样返回
   c) 如果 query 是口语化长句，提取 3-5 个核心学术关键词作为改写结果
   d) 改写后的 query 总字数不超过 40 个字
   e) 不要补充同义词，不要添加原文没有的术语
3. 若覆盖度为 low 或 out_of_domain，suggestion 提示语料库局限；否则为空字符串

## 输出格式
只输出一行 JSON:
{"domain":"领域名","coverage":"high|medium|low|out_of_domain","rewritten_query":"精简后的query","keywords":["词1","词2","词3"],"suggestion":""}"""


@dataclass
class IntentResult:
    domain: str = ""
    coverage: str = ""  # high / medium / low / out_of_domain
    rewritten_query: str = ""
    keywords: list[str] = field(default_factory=list)
    suggestion: str = ""


GENERIC_PROMPT = """你是通用文档检索的查询重写助手。

任务：将用户口语化查询重写为更适合全文检索+语义检索的形式（展开缩写、补充同义词、标准化术语），保留原意。

输出格式：只输出一行 JSON，不要任何额外文字:
{"domain":"通用文档","coverage":"unknown","rewritten_query":"重写后的query","keywords":["词1","词2","词3"],"suggestion":""}"""


def analyze_intent(
    query: str,
    last_context: str = "",
    is_generic: bool = False,
    timeout: float = 10.0,
) -> IntentResult:
    """
    分析用户查询意图，返回分类结果和重写后的 query。

    参数:
        query: 用户原始查询
        last_context: 最近对话上下文（用于指代消解），格式：
                      用户：xxx\nAI：xxx\n用户：xxx
        timeout: API 超时秒数

    返回:
        IntentResult，失败时返回原 query 直通的默认结果
    """
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("your-"):
        return IntentResult(rewritten_query=query)

    from src.llm import get_chat_model

    chat = get_chat_model(model=DEEPSEEK_INTENT_MODEL, temperature=0.0)

    system_prompt = GENERIC_PROMPT if is_generic else SYSTEM_PROMPT

    user_message = query
    if last_context:
        user_message = f"上轮对话：\n{last_context}\n\n当前提问：{query}\n\n请根据上轮对话，将当前提问中可能存在的指代词（如\"它\"\"这个\"\"上面\"）替换为具体内容，重写为独立的检索查询。"

    try:
        resp = chat.bind(response_format={"type": "json_object"}).invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ],
        )
    except Exception as e:
        logger.warning("DeepSeek API 调用失败: %s", e)
        return IntentResult(rewritten_query=query)

    try:
        obj = json.loads(resp.content)
        return IntentResult(
            domain=obj.get("domain", ""),
            coverage=obj.get("coverage", ""),
            rewritten_query=obj.get("rewritten_query", query),
            keywords=obj.get("keywords", []),
            suggestion=obj.get("suggestion", ""),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("DeepSeek 响应解析失败: %s | content: %s", e, resp.content[:200])
        return IntentResult(rewritten_query=query)
