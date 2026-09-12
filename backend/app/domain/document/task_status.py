"""文档任务状态机契约。

`TaskStatus` 六态（值与前端 `types/knowledge.ts` 逐字一致）与显式状态迁移表。
DB 层落 SQL Enum/CHECK，领域层在此校验非法跳转。
纯 stdlib，零外部依赖，可独立单测。
"""
from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


# 合法迁移表（非法跳转抛 InvalidStatusTransition）
# PENDING→PROCESSING(提交成功)→PARSED(mineru done)→INDEXING(触发索引)→READY|FAILED
# 任一步→FAILED(带 error)；FAILED→PENDING(重试)；PARSED→PENDING(重跑)
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.PROCESSING, TaskStatus.FAILED},
    TaskStatus.PROCESSING: {TaskStatus.PARSED, TaskStatus.FAILED},
    TaskStatus.PARSED: {TaskStatus.INDEXING, TaskStatus.FAILED, TaskStatus.PENDING},
    TaskStatus.INDEXING: {TaskStatus.READY, TaskStatus.FAILED},
    TaskStatus.READY: set(),
    TaskStatus.FAILED: {TaskStatus.PENDING},
}


class InvalidStatusTransition(Exception):
    """非法状态迁移。"""


def _coerce(value: TaskStatus | str) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    try:
        return TaskStatus(value)
    except ValueError as e:
        raise InvalidStatusTransition(f"未知状态值: {value!r}") from e


def transition(current: TaskStatus | str, target: TaskStatus | str) -> TaskStatus:
    """校验并执行状态迁移，非法跳转抛 InvalidStatusTransition。"""
    cur = _coerce(current)
    tgt = _coerce(target)
    if tgt not in ALLOWED_TRANSITIONS[cur]:
        raise InvalidStatusTransition(f"非法状态迁移: {cur.value} → {tgt.value}")
    return tgt
