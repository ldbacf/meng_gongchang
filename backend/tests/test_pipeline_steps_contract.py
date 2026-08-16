"""pipeline_steps 契约测试。"""
from __future__ import annotations

import pytest

from app.domain.document.pipeline_steps import (
    PIPELINE_STEPS_ORDER,
    PipelineStepsError,
    default_pipeline_steps,
    validate,
)


def test_default_has_all_steps():
    steps = default_pipeline_steps()
    assert list(steps.keys()) == PIPELINE_STEPS_ORDER
    for st in steps.values():
        assert st["status"] == "pending"
        assert "ts" in st


def test_validate_valid_steps():
    steps = default_pipeline_steps()
    steps["upload"]["status"] = "done"
    out = validate(steps)
    assert out["upload"]["status"] == "done"
    # 返回的是副本，不污染原对象
    assert steps["upload"]["status"] == "done"


def test_validate_rejects_unknown_key():
    steps = default_pipeline_steps()
    steps["bogus"] = {"status": "done", "ts": 0.0}
    with pytest.raises(PipelineStepsError, match="未知步骤"):
        validate(steps)


def test_validate_rejects_invalid_status():
    steps = default_pipeline_steps()
    steps["mineru"]["status"] = "parsed"  # 非法值（污染 JSONB 的旧行为）
    with pytest.raises(PipelineStepsError, match="非法 status"):
        validate(steps)


def test_validate_rejects_missing_ts():
    steps = default_pipeline_steps()
    del steps["mineru"]["ts"]
    with pytest.raises(PipelineStepsError, match="缺少 ts"):
        validate(steps)


def test_validate_rejects_missing_step():
    steps = default_pipeline_steps()
    del steps["milvus"]
    with pytest.raises(PipelineStepsError, match="缺少步骤"):
        validate(steps)


def test_validate_rejects_non_dict():
    with pytest.raises(PipelineStepsError):
        validate(None)
    with pytest.raises(PipelineStepsError):
        validate("nope")
