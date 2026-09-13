"""rag_steps 单工厂 — 四步 metric 统一构建（S-4.6，消 3×2 手写字典）。

契约（总需求 §4.2.2 / §7.7）：intent / retrieval / fusion / answer 四步 metrics
字段唯一真相源。图节点只传数据，由 `build_rag_step(key, ...)` 统一产出
`{status, title, elapsed_ms, metrics}` —— 杜绝多处手写字典导致的字段漂移。

`degraded` 字段：任一步降级（intent 失败直通 / rerank 失败保序 / 检索异常）显式置
true，对应 A-4.5 / T-4.6（降级可观测，不再静默）。
"""
from __future__ import annotations

STEP_TITLES = {
    "intent": "意图识别",
    "retrieval": "混合检索",
    "fusion": "融合重排",
    "answer": "生成回答",
}

# fusion 的 reranker 展示短名（配置项 `siliconflow_rerank_model` 为 "Qwen/Qwen3-Reranker-4B"，
# 这里省去 org 前缀保持 UI 简洁 —— 属于**展示裁剪**，若要一并改为配置驱动，UI 文案会变成带
# 前缀的全名）。answer 的模型名不在此处：它必须取自配置，见 `_answer_metrics`。
STEP_MODELS = {
    "fusion": "Qwen3-Reranker-4B",
}


def _intent_metrics(
    *, domain="", coverage="", rewritten_query="", keywords=None,
    suggestion="", degraded=False,
) -> dict:
    return {
        "domain": domain or "通用",
        "coverage": coverage or "unknown",
        "rewritten_query": rewritten_query or "",
        "keywords": keywords or [],
        "suggestion": suggestion or "",
        "degraded": degraded,
    }


def _retrieval_metrics(
    *, milvus_hits=0, es_hits=0, after_dedup=0, routing="", degraded=False,
) -> dict:
    return {
        "milvus_hits": milvus_hits,
        "es_hits": es_hits,
        "after_dedup": after_dedup,
        "routing": routing or "es_only",
        "degraded": degraded,
    }


def _fusion_metrics(
    *, input_count=0, output_count=0, top_scores=None, degraded=False,
) -> dict:
    return {
        "input_count": input_count,
        "output_count": output_count,
        "model": STEP_MODELS["fusion"],
        "top_scores": top_scores or [],
        "degraded": degraded,
    }


def _answer_metrics(
    *, context_chunks=0, total_tokens=0, total_elapsed_ms=0, degraded=False,
) -> dict:
    """answer 步 metrics。`model` **取自配置**（`settings.deepseek_answer_model`）。

    这里曾硬编码 "DeepSeek-V4-Pro"，而真正决定用哪个模型的 `llm_answer` 读的是 settings
    —— 同一个人名写两份，于是配置早已是 `deepseek-v4-flash` 时，UI 面板仍显示 V4-Pro，
    **谎报所用模型**。模型名只有一个真相源：配置。
    """
    from app.infrastructure.settings import get_settings

    return {
        "model": get_settings().deepseek_answer_model,
        "context_chunks": context_chunks,
        "total_tokens": total_tokens,
        "total_elapsed_ms": total_elapsed_ms,
        "degraded": degraded,
    }


_BUILDERS = {
    "intent": _intent_metrics,
    "retrieval": _retrieval_metrics,
    "fusion": _fusion_metrics,
    "answer": _answer_metrics,
}


def build_rag_step(
    key: str,
    *,
    status: str = "done",
    title: str = "",
    elapsed_ms: int = 0,
    **metric_kwargs,
) -> dict:
    """单一工厂：`key` 步 → `{status, title, elapsed_ms, metrics}`。

    `key` 必在 STEP_TITLES；`metric_kwargs` 按 key 分发到对应 metrics 构建器。
    非法 key 抛 KeyError（防字段漂移写错步名）。
    """
    if key not in _BUILDERS:
        raise KeyError(f"unknown rag step: {key}")
    metrics = _BUILDERS[key](**metric_kwargs)
    return {
        "status": status,
        "title": title or STEP_TITLES[key],
        "elapsed_ms": int(elapsed_ms),
        "metrics": metrics,
    }


# 步骤顺序（恰为 SSE 契约的 4 步；cite/done/error 不是业务步，不经此工厂）
STEP_KEYS = tuple(STEP_TITLES.keys())
