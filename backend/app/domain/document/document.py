"""Document 聚合根（轻量领域门面，纯 stdlib）。

承载文档任务状态机（`TaskStatus` + 显式迁移表）与 pipeline 步骤校验。
- `transition_to()`：流水线内正常迁移（走 `transition()`，非法抛 InvalidStatusTransition）。
- `reset()`：人为重开（重传/重扫/重试），**无条件**写 PENDING，非状态机迁移。

ORM（`app/infrastructure/db/models.DocumentTask`）提供同语义的 `set_status/reset`，本类供阶段 3 图节点使用。
"""
from __future__ import annotations

from app.domain.document.pipeline_steps import PipelineSteps
from app.domain.document.task_status import InvalidStatusTransition, TaskStatus, transition


class Document:
    def __init__(
        self,
        status: TaskStatus | str = TaskStatus.PENDING,
        pipeline_steps: PipelineSteps | None = None,
    ):
        self._status = TaskStatus(status) if not isinstance(status, TaskStatus) else status
        self.pipeline_steps = pipeline_steps

    @property
    def status(self) -> TaskStatus:
        return self._status

    def transition_to(self, target: TaskStatus | str) -> TaskStatus:
        """正常流水线迁移（校验迁移表）。"""
        self._status = transition(self._status, target)
        return self._status

    def reset(self) -> TaskStatus:
        """人为重开（非状态机迁移）：无条件回到 PENDING。"""
        self._status = TaskStatus.PENDING
        return self._status
