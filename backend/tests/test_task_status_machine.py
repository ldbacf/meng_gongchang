"""TaskStatus 状态机测试。"""
from __future__ import annotations

import pytest

from app.domain.document.task_status import (
    ALLOWED_TRANSITIONS,
    InvalidStatusTransition,
    TaskStatus,
    transition,
)


def test_all_valid_transitions_pass():
    for cur, targets in ALLOWED_TRANSITIONS.items():
        for tgt in targets:
            assert transition(cur, tgt) == tgt


def test_invalid_transition_raises():
    with pytest.raises(InvalidStatusTransition):
        transition(TaskStatus.PENDING, TaskStatus.READY)
    with pytest.raises(InvalidStatusTransition):
        transition(TaskStatus.PROCESSING, TaskStatus.INDEXING)
    with pytest.raises(InvalidStatusTransition):
        transition(TaskStatus.READY, TaskStatus.PENDING)
    with pytest.raises(InvalidStatusTransition):
        transition(TaskStatus.INDEXING, TaskStatus.PARSED)


def test_accepts_string_values():
    assert transition("pending", "processing") == TaskStatus.PROCESSING


def test_unknown_status_raises():
    with pytest.raises(InvalidStatusTransition):
        transition(TaskStatus.PENDING, "bogus")


def test_enum_values_match_frontend_contract():
    # 与前端 types/knowledge.ts 逐字一致
    assert [s.value for s in TaskStatus] == [
        "pending", "processing", "parsed", "indexing", "ready", "failed",
    ]
