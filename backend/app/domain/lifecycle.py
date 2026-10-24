"""步骤状态契约 —— 全后端唯一真相源。

## 为什么需要它

同一个"进度"概念在项目里有三套不同的取值，之前各自手写字符串，导致：

- 文档流水线写 `done`，RAG 步骤也写 `done`
- 前端某处把 `done` 映射成 `completed`，落到历史消息里就出现了两种值
- 结果：历史会话回放时勾选态丢失、步骤点不开（实际发生的线上问题）

现在只保留**一个**步骤状态枚举，RAG 步骤与文档流水线共用；任何写入方都必须
经过 `normalize_step_status()`，非法值不会被写进 JSONB / SSE。

## 三套状态机（不要再混）

1. **步骤级 `StepStatus`**（本模块）：`pending / running / done / failed / skipped`
   用于 `rag_steps`（RAG 四步）与 `pipeline_steps`（文档六步）。
2. **文档级 `DocStatus`**：`pending / processing / parsed / indexing / ready / failed`
   是**粗粒度阶段**（整篇文档现在处于哪一步），不是步骤状态，见 `infrastructure/db/models.py`。
3. **任务队列状态**：属于 Redis Stream 消费语义，与本模块无关。

前端在 `types/step.ts` 里镜像同一份枚举，且**只在读取边界做一次归一**
（legacy `completed` → `done`），其余地方一律比较 `done`。

纯 stdlib，零外部依赖（domain 层约定）。
"""
from __future__ import annotations

from typing import Literal, get_args

# ── 步骤状态 ────────────────────────────────────────────────

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]

#: 合法取值集合（供校验器直接使用）
STEP_STATUSES: frozenset[str] = frozenset(get_args(StepStatus))

#: 终态：不会再变化，可安全落库/回放
TERMINAL_STEP_STATUSES: frozenset[str] = frozenset({"done", "failed", "skipped"})

#: 历史遗留别名。早期前端把 `done` 读成 `completed`，这些值可能残留在旧数据里；
#: 读到时就地归一，写入方永远不该产生它们。
LEGACY_STEP_ALIASES: dict[str, str] = {
    "completed": "done",
    "complete": "done",
    "success": "done",
    "error": "failed",
}


def normalize_step_status(value: object, *, default: StepStatus = "pending") -> StepStatus:
    """把任意输入归一成合法的 `StepStatus`。

    未知值**不抛异常**：历史数据可能来自更早的版本，宁可降级成 `pending`
    让 UI 还能渲染，也不要因为一条脏数据让整个会话打不开。
    """
    if not isinstance(value, str):
        return default
    v = value.strip().lower()
    if not v:
        return default
    v = LEGACY_STEP_ALIASES.get(v, v)
    return v if v in STEP_STATUSES else default  # type: ignore[return-value]


def is_terminal(value: object) -> bool:
    """该步骤是否已进入终态。"""
    return normalize_step_status(value) in TERMINAL_STEP_STATUSES
