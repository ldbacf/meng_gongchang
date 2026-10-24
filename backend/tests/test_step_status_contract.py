"""步骤状态契约回归测试 —— `app.domain.lifecycle` 是唯一真相源。

背景（线上问题）：文档流水线写 `done`、RAG 步骤也写 `done`，但前端某处把
`done` 映射成 `completed` 并写进了类型；历史会话回放时勾选态因此丢失、
步骤点不开。修复后统一到 `StepStatus`，本文件锁住这条契约：

1. 合法取值只有一个集合
2. 历史别名（completed/success/error）只在**读取边界**归一，写入方不产生
3. SSE 帧与 Pydantic schema 都不可能发出非法值
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.rag.rag_metrics import build_rag_step
from app.domain.document.pipeline_steps import (
    PIPELINE_STEPS_ORDER,
    VALID_STATUS,
    PipelineStepsError,
    default_pipeline_steps,
    validate,
)
from app.domain.lifecycle import (
    STEP_STATUSES,
    TERMINAL_STEP_STATUSES,
    is_terminal,
    normalize_step_status,
)
from app.domain.sse import frame_step
from app.interface.schemas import MessageResponse, RagStepSchema


# ── 单一取值集合 ────────────────────────────────────────────


def test_pipeline_and_lifecycle_share_one_source():
    """pipeline_steps 不再自己定义一套取值。"""
    assert VALID_STATUS == STEP_STATUSES


def test_canonical_values():
    assert STEP_STATUSES == {"pending", "running", "done", "failed", "skipped"}
    assert TERMINAL_STEP_STATUSES == {"done", "failed", "skipped"}


# ── 归一 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("done", "done"),
        ("DONE", "done"),
        ("  pending  ", "pending"),
        ("completed", "done"),   # 历史别名
        ("complete", "done"),
        ("success", "done"),
        ("error", "failed"),
    ],
)
def test_normalize_known_and_legacy(raw, expected):
    assert normalize_step_status(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "weird", 123, {"a": 1}])
def test_normalize_unknown_falls_back_to_pending(raw):
    """脏数据不该让整个会话打不开，降级成 pending 即可。"""
    assert normalize_step_status(raw) == "pending"


def test_is_terminal():
    assert is_terminal("done") and is_terminal("completed") and is_terminal("failed")
    assert not is_terminal("pending") and not is_terminal("running")


# ── 写入方：RAG 步骤 ───────────────────────────────────────


def test_build_rag_step_defaults_to_done():
    assert build_rag_step("intent").get("status") == "done"


def test_build_rag_step_normalizes_legacy_status():
    """即便调用方传了 `completed`，落库/出帧也必须是 `done`。"""
    assert build_rag_step("intent", status="completed")["status"] == "done"


def test_build_rag_step_rejects_unknown_status_to_default():
    assert build_rag_step("intent", status="whatever")["status"] == "done"


# ── 出帧：SSE ──────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["done", "pending", "completed", "WEIRD", ""])
def test_frame_step_only_emits_canonical(raw):
    frame = frame_step("intent", raw)
    assert frame["s"] in STEP_STATUSES
    assert frame["v"] == 1 and frame["t"] == "step"


# ── 回放：Pydantic schema ──────────────────────────────────


def test_schema_accepts_canonical():
    assert RagStepSchema(status="done", title="意图识别").status == "done"
    assert RagStepSchema(status="pending", title="x").status == "pending"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("completed", "done"),   # 6~8 月旧版后端留下的值（库里实存 44 处）
        ("complete", "done"),
        ("success", "done"),
        ("error", "failed"),
        ("DONE", "done"),        # 大小写
        ("weird", "pending"),    # 未知值降级，不让会话打不开
        (None, "pending"),
    ],
)
def test_schema_normalizes_instead_of_raising(raw, expected):
    """读取边界归一：历史脏数据不能让 `GET messages` 整个 500。"""
    assert RagStepSchema(status=raw, title="x").status == expected


def test_schema_field_is_the_enum():
    """OpenAPI 里暴露的必须是 5 值枚举，而不是自由字符串。"""
    from typing import get_args

    assert set(get_args(RagStepSchema.model_fields["status"].annotation)) == STEP_STATUSES


def test_message_response_tolerates_legacy_payload():
    """整条历史消息（含 completed）能被解析，且输出规范化。"""
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "role": "ai",
        "content": "x",
        "citations": None,
        "created_at": "2026-06-12T06:15:38Z",
        "rag_steps": {
            "intent": {"status": "completed", "title": "意图识别"},
            "retrieval": {"status": "done", "title": "混合检索"},
        },
    }
    msg = MessageResponse.model_validate(payload)
    assert msg.rag_steps is not None
    assert msg.rag_steps["intent"].status == "done"
    assert msg.rag_steps["retrieval"].status == "done"


# ── 文档流水线校验器 ───────────────────────────────────────


def test_default_pipeline_steps_shape():
    steps = default_pipeline_steps()
    assert list(steps) == PIPELINE_STEPS_ORDER
    assert all(s["status"] == "pending" and "ts" in s for s in steps.values())


def test_validate_normalizes_legacy_alias():
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "completed", "ts": 1.0}  # type: ignore[typeddict-item]
    out = validate(steps)
    assert out["upload"]["status"] == "done"


def test_validate_rejects_unknown_status():
    steps = default_pipeline_steps()
    steps["upload"] = {"status": "whatever", "ts": 1.0}  # type: ignore[typeddict-item]
    with pytest.raises(PipelineStepsError):
        validate(steps)
