"""pipeline_steps 数据契约 — TypedDict + 校验器。

固定六步：upload / mineru / chunking / embedding / es_write / milvus。
图（阶段 3/4）是唯一写入方；本模块校验器拒绝未知 key、非法 status、缺 ts，
杜绝 worker 写 `task.status.lower()` 之类污染 JSONB 的旧行为。
纯 stdlib，零外部依赖。
"""
from __future__ import annotations

import datetime as _dt
from typing import Literal, TypedDict

PIPELINE_STEPS_ORDER: list[str] = [
    "upload", "mineru", "chunking", "embedding", "es_write", "milvus",
]
VALID_STATUS: set[str] = {"pending", "running", "done", "failed", "skipped"}

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


class StepState(TypedDict, total=False):
    status: StepStatus
    ts: float
    target_index: str | None
    target_collection: str | None
    count: int | None
    error: str | None


class PipelineSteps(TypedDict):
    upload: StepState
    mineru: StepState
    chunking: StepState
    embedding: StepState
    es_write: StepState
    milvus: StepState


class PipelineStepsError(Exception):
    """pipeline_steps 不符合契约。"""


def default_pipeline_steps() -> PipelineSteps:
    """返回六步初始（pending）结构，ts 为当前 UTC 时间戳。"""
    now = _dt.datetime.now(_dt.timezone.utc).timestamp()
    return {  # type: ignore[return-value]
        step: {"status": "pending", "ts": now}
        for step in PIPELINE_STEPS_ORDER
    }


def validate(steps: dict | None) -> dict:
    """校验并返回规范化副本；非法 key / status / 缺 ts 抛 PipelineStepsError。"""
    if steps is None:
        raise PipelineStepsError("pipeline_steps 不能为空")
    if not isinstance(steps, dict):
        raise PipelineStepsError(f"pipeline_steps 必须是 dict，得到 {type(steps).__name__}")

    unknown = [k for k in steps if k not in PIPELINE_STEPS_ORDER]
    if unknown:
        raise PipelineStepsError(f"未知步骤 key: {unknown}")

    out: dict = {}
    for step in PIPELINE_STEPS_ORDER:
        if step not in steps:
            raise PipelineStepsError(f"缺少步骤 {step!r}")
        st = steps[step]
        if not isinstance(st, dict):
            raise PipelineStepsError(f"步骤 {step!r} 状态必须是 dict")
        if st.get("status") not in VALID_STATUS:
            raise PipelineStepsError(f"步骤 {step!r} 非法 status: {st.get('status')!r}")
        if "ts" not in st:
            raise PipelineStepsError(f"步骤 {step!r} 缺少 ts")
        out[step] = dict(st)
    return out
