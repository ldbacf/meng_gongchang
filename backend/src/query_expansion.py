"""
查询术语扩展模块 — DeepSeek-V4-Flash 将口语化医疗问题转换为专业检索词

解决场景：
  用户说 "一天吃七八种药" → 应匹配 "多重用药 药物相互作用 共病"
  用户说 "冬天咳嗽喘不上气" → 应匹配 "慢性阻塞性肺疾病 COPD 呼吸困难"

用法:
    from src.query_expansion import expand_query

    expanded = expand_query("一天吃七八种药会不会互相影响")
    print(expanded)  # 多重用药 药物相互作用 共病
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_INTENT_MODEL

logger = logging.getLogger("query_expansion")

SYSTEM_PROMPT = """你是一名医学检索专家，负责将患者的日常口语描述转换为专业医学检索关键词。

## 规则
1. 将口语化症状、疾病描述转换为标准医学术语
2. 补充患者可能不知道但文献中常用的专业术语/同义词
3. 保留所有核心实体（疾病名、药名、检查名、科室名）
4. 只输出关键词，用空格分隔
5. 最多 6 个关键词，必须精准
6. 如果 query 已经是专业简洁形式（含≥2个医学术语），直接原样返回
7. 不要输出解释、不要加标点、不要换行

## 转换示例
- "一天要吃七八种药，会不会互相影响"           → "多重用药 药物相互作用 共病 老年人用药 STOPP标准"
- "一到冬天就咳嗽咳痰，走路快了喘不上气"       → "慢性阻塞性肺疾病 COPD 呼吸困难 肺功能检查"
- "记性越来越差，刚说过的话转头就忘"           → "轻度认知障碍 认知功能下降 痴呆 老年"
- "血压高血糖高血脂高，要一起管"                 → "三高共管 高血压 糖尿病 血脂异常 综合管理"
- "上次脑梗后走路不稳说话含糊"                   → "脑卒中 脑梗死 康复 运动功能障碍 言语障碍"
- "得了好几种慢性病，降压药降糖药都在吃"         → "共病 多重慢性病 多重用药 综合管理 全科医学"
- "做了心脏支架，怕血管再堵"                     → "冠心病 冠状动脉支架 二级预防 心脏康复"
- "怀孕后总想哭，对什么都没兴趣"                 → "产后抑郁 围产期抑郁 心理健康 情绪障碍"

## 输出格式
只输出一行 JSON:
{"expanded_query": "关键词1 关键词2 关键词3 ...的字符串"}
"""


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
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=query),
            ],
        )
    except Exception as e:
        logger.warning("DeepSeek API 调用失败: %s", e)
        return query

    try:
        obj = json.loads(resp.content)
        expanded = obj.get("expanded_query", "").strip()
        if expanded:
            return expanded
        return query
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("解析失败: %s | content: %s", e, resp.content[:200])
        return query
