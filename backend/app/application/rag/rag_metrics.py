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

STEP_MODELS = {
    "fusion": "Qwen3-Reranker-4B",
    "answer": "DeepSeek-V4-Pro",
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
    return {
        "model": STEP_MODELS["answer"],
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
