"""rag_steps 单工厂 — 四步 metric 统一构建（S-4.6，消 3×2 手写字典）。

契约（总需求 §4.2.2 / §7.7）：intent / retrieval / fusion / answer 四步 metrics
字段唯一真相源。图节点只传数据，由 `build_rag_step(key, ...)` 统一产出
`{status, title, elapsed_ms, metrics}` —— 杜绝多处手写字典导致的字段漂移。

`degraded` 字段：任一步降级（intent 失败直通 / rerank 失败保序 / 检索异常）显式置
true，对应 A-4.5 / T-4.6（降级可观测，不再静默）。

## `degraded_reason`：让「没找到」和「检索挂了」长得不一样

`degraded=True` 只说明「这一步没正常工作」，没说为什么。真实事故里
Milvus 因为字段名写错抛了 `MilvusException: field title not exist`，被
`except Exception: degraded = True` 吞掉 —— 向量路恒 0 条，rerank 分数被拉低，
最终回答「知识库中未找到相关文献」。**用户看到的是"这个库确实没有"，而
真相是"检索链路坏了"**，两者在界面上完全相同。

所以降级时额外带上 `degraded_reason`（异常类名 + 首行消息），前端可据此把
「本次为降级结果」显式标出来。

**只在降级时出现**：不降级时该 key 不存在，保持既有字段集契约不变
（`test_sse_rag.py::test_metrics_single_source_fields` 对键集做精确断言）。
"""
from __future__ import annotations

from app.domain.lifecycle import StepStatus, normalize_step_status

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

#: 降级原因的最大长度（异常消息可能很长，而它要进 SSE 帧与数据库 JSONB）
_MAX_REASON_CHARS = 200


def describe_exception(exc: BaseException | None) -> str:
    """把异常压成一行可读原因：`类名: 首行消息`。

    只取首行：pymilvus 的异常消息里带多行栈式描述，整段塞进 metrics 既没人看
    也撑大 SSE 帧。给不出异常（如"静默全零分"这类非异常降级）时返回空串，
    由调用方自己给一句说明。
    """
    if exc is None:
        return ""
    name = type(exc).__name__
    msg = str(exc).strip().splitlines()
    first = msg[0].strip() if msg else ""
    text = f"{name}: {first}" if first else name
    return text[:_MAX_REASON_CHARS]


def _with_reason(metrics: dict, degraded_reason: str) -> dict:
    """降级原因非空才写进 metrics（不降级时保持键集不变）。"""
    if degraded_reason:
        metrics["degraded_reason"] = degraded_reason
    return metrics


def _intent_metrics(
    *, domain="", coverage="", rewritten_query="", keywords=None,
    suggestion="", degraded=False, degraded_reason="",
) -> dict:
    return _with_reason({
        "domain": domain or "通用",
        "coverage": coverage or "unknown",
        "rewritten_query": rewritten_query or "",
        "keywords": keywords or [],
        "suggestion": suggestion or "",
        "degraded": degraded,
    }, degraded_reason)


def _retrieval_metrics(
    *, milvus_hits=0, es_hits=0, after_dedup=0, routing="", degraded=False,
    degraded_reason="",
) -> dict:
    return _with_reason({
        "milvus_hits": milvus_hits,
        "es_hits": es_hits,
        "after_dedup": after_dedup,
        "routing": routing or "es_only",
        "degraded": degraded,
    }, degraded_reason)


def _fusion_metrics(
    *, input_count=0, output_count=0, top_scores=None, degraded=False,
    degraded_reason="",
) -> dict:
    return _with_reason({
        "input_count": input_count,
        "output_count": output_count,
        "model": STEP_MODELS["fusion"],
        "top_scores": top_scores or [],
        "degraded": degraded,
    }, degraded_reason)


def _answer_metrics(
    *, context_chunks=0, total_tokens=0, total_elapsed_ms=0, degraded=False,
    route="retrieval", degraded_reason="",
) -> dict:
    """answer 步 metrics。`model` **取自配置**（`settings.deepseek_answer_model`）。

    这里曾硬编码 "DeepSeek-V4-Pro"，而真正决定用哪个模型的 `llm_answer` 读的是 settings
    —— 同一个人名写两份，于是配置早已是 `deepseek-v4-flash` 时，UI 面板仍显示 V4-Pro，
    **谎报所用模型**。模型名只有一个真相源：配置。
    """
    from app.infrastructure.settings import get_settings

    return _with_reason({
        "model": get_settings().deepseek_answer_model,
        "context_chunks": context_chunks,
        "total_tokens": total_tokens,
        "total_elapsed_ms": total_elapsed_ms,
        "route": route,
        "degraded": degraded,
    }, degraded_reason)


_BUILDERS = {
    "intent": _intent_metrics,
    "retrieval": _retrieval_metrics,
    "fusion": _fusion_metrics,
    "answer": _answer_metrics,
}


def build_rag_step(
    key: str,
    *,
    status: StepStatus | str = "done",
    title: str = "",
    elapsed_ms: int = 0,
    **metric_kwargs,
) -> dict:
    """单一工厂：`key` 步 → `{status, title, elapsed_ms, metrics}`。

    `key` 必在 STEP_TITLES；`metric_kwargs` 按 key 分发到对应 metrics 构建器。
    非法 key 抛 KeyError（防字段漂移写错步名）。
    `status` 一律归一成 `app.domain.lifecycle.StepStatus`（`done` 是规范值）。
    """
    if key not in _BUILDERS:
        raise KeyError(f"unknown rag step: {key}")
    metrics = _BUILDERS[key](**metric_kwargs)
    return {
        "status": normalize_step_status(status, default="done"),
        "title": title or STEP_TITLES[key],
        "elapsed_ms": int(elapsed_ms),
        "metrics": metrics,
    }


# 步骤顺序（恰为 SSE 契约的 4 步；cite/done/error 不是业务步，不经此工厂）
STEP_KEYS = tuple(STEP_TITLES.keys())
