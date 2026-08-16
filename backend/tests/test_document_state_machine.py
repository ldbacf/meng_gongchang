"""Document 状态机门面：set_status（迁移表校验）/ reset（人为重开）。"""
from __future__ import annotations

import pytest

from app.domain.document.document import Document
from app.domain.document.task_status import InvalidStatusTransition, TaskStatus


def test_document_transition_to_valid():
    d = Document(TaskStatus.PENDING)
    d.transition_to(TaskStatus.PROCESSING)
    assert d.status is TaskStatus.PROCESSING
    d.transition_to(TaskStatus.PARSED)
    assert d.status is TaskStatus.PARSED


def test_document_transition_to_invalid():
    d = Document(TaskStatus.PENDING)
    with pytest.raises(InvalidStatusTransition):
        d.transition_to(TaskStatus.READY)  # PENDING→READY 非法


def test_document_reset_unconditional():
    """reset 无条件回 PENDING（人为重开，非状态机迁移，READY 也可 reset）。"""
    d = Document(TaskStatus.READY)
    d.reset()
    assert d.status is TaskStatus.PENDING


def test_document_accepts_str_status():
    d = Document("processing")
    assert d.status is TaskStatus.PROCESSING
