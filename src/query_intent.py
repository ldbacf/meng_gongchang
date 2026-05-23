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

SYSTEM_PROMPT = """你是医学文献检索的意图识别助手。你的任务是分析用户的医学查询，并判断当前语料库能否回答。

## 语料库覆盖地图
当前语料库为《中国全科医学》期刊的 1248 篇论文，各领域覆盖度如下：

### 高覆盖 (语料充足，可直接检索)
- 高血压 (降压药物、血压管理、靶器官损害)
- 糖尿病 / 2型糖尿病 (血糖管理、并发症、生活方式干预)
- 心血管疾病 (冠心病、心衰、血脂异常、抗血小板治疗)
- 慢性病管理 / 慢性病共病 (多病共存、综合防控)
- 全科医学 / 基层医疗 (家庭医生签约、分级诊疗、社区卫生)
- 临床指南 / 专家共识 (诊疗规范、循证医学)
- Meta分析 / 系统评价 / 影响因素分析
- 脑卒中 (缺血性脑卒中、康复、二级预防)

### 中等覆盖 (部分语料，可尝试检索)
- 老年人健康 (老年综合征、衰弱、多重用药)
- 中医药 / 中西医结合 (中药疗效、中医辨证)
- 呼吸系统 (COPD、哮喘、社区获得性肺炎)
- 脓毒症 / 感染性疾病
- 慢性肾病 (CKD、透析、肾性贫血)
- 精神心理 (抑郁、焦虑、睡眠障碍)

### 低覆盖 (语料不足，结果可能有限)
- 儿科 (偏向儿童用药政策，非临床诊疗)
- 肿瘤 (偏向筛查和姑息治疗，非放化疗细节)
- 消化系统 (肝病、功能性胃肠病)
- 妇产科

### 无覆盖 (语料库基本不涉及)
- 外科手术技术
- 急诊急救流程
- 罕见病
- 基础医学研究 (动物实验、分子机制)
- 非医学类问题

## 任务
1. 判断用户 query 属于哪个领域
2. 评估语料库对该领域的覆盖度: high / medium / low / out_of_domain
3. 将口语化 query 重写为检索友好的形式 (展开缩写、补充同义词、标准化术语，保留原意)
4. 若覆盖度为 low 或 out_of_domain，生成一句友好的提示，说明语料库局限；若 high/medium 则 suggestion 为空字符串

## 输出格式
只输出一行 JSON，不要任何额外文字:
{"domain":"领域名","coverage":"high|medium|low|out_of_domain","rewritten_query":"重写后的query","keywords":["词1","词2","词3"],"suggestion":""}"""


@dataclass
class IntentResult:
    domain: str = ""
    coverage: str = ""  # high / medium / low / out_of_domain
    rewritten_query: str = ""
    keywords: list[str] = field(default_factory=list)
    suggestion: str = ""


def analyze_intent(
    query: str,
    last_context: str = "",
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

    user_message = query
    if last_context:
        user_message = f"上轮对话：\n{last_context}\n\n当前提问：{query}\n\n请根据上轮对话，将当前提问中可能存在的指代词（如\"它\"\"这个\"\"上面\"）替换为具体内容，重写为独立的检索查询。"

    try:
        resp = chat.bind(response_format={"type": "json_object"}).invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
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
