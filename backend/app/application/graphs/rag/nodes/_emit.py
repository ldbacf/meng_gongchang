"""图节点 → SSE 自定义事件发射（C7：token 走 on_custom_event；step/cite/done 同理）。

`astream_events(version='v2')` 消费端在 `on_custom_event` 里按 `event['name']` 分流：
- `step`  → 帧 `{v, t:step, k, s, elapsed_ms, metrics}`
- `token` → 帧 `{v, t:text, c}`
- `cite`  → 帧 `{v, t:cite, citations:[...]}`
- `done`  → 帧 `{v, t:done, conversation_id, message_id}`

统一经 `adispatch_custom_event`（async）——节点在 async 图上下文内调用即可派发。
"""
from __future__ import annotations

from langchain_core.callbacks import adispatch_custom_event


async def _emit(name: str, payload: dict) -> None:
    """best-effort 派发自定义事件（C7）。

    节点在 `astream_events(v2)` 运行上下文内调用才可派发（有 parent_run_id）；
    直接调用节点（单测/无运行上下文）无 parent_run_id 会抛 RuntimeError——此处吞掉，
    SSE 帧丢失但管线不崩。生产图内必在上下文内，正常派发。
    """
    try:
        await adispatch_custom_event(name, payload)
    except RuntimeError:
        pass


async def emit_step(k: str, s: str, elapsed_ms: int = 0, metrics: dict | None = None) -> None:
    await _emit("step", {
        "k": k, "s": s, "elapsed_ms": elapsed_ms, "metrics": metrics or {},
    })


async def emit_text(c: str) -> None:
    await _emit("token", {"c": c})


async def emit_cite(citations: list[dict]) -> None:
    await _emit("cite", {"citations": citations})


async def emit_done(conversation_id: str, message_id: str) -> None:
    await _emit("done", {
        "conversation_id": conversation_id, "message_id": message_id,
    })
