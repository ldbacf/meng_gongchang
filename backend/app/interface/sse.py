"""SSE v1 投影器（契约 7.7）— 帧构建 + 序列化（单一真相源）。

每帧带版本信封 `{"v":1, ...}`（向后兼容旧前端 useSSE，旧字段保留）。
帧类型：step / text / cite / done / error / heartbeat。
metrics 由 `app/application/rag/rag_metrics.build_rag_step` 单工厂产出（S-4.6）。
"""
from __future__ import annotations

import json
from typing import Any


def envelope(t: str, **fields) -> dict:
    """版本信封：`{v:1, t:..., **fields}`。"""
    return {"v": 1, "t": t, **fields}


def frame_step(k: str, s: str, elapsed_ms: int = 0, metrics: dict | None = None) -> dict:
    return envelope("step", k=k, s=s, elapsed_ms=elapsed_ms, metrics=metrics or {})


def frame_text(c: str) -> dict:
    return envelope("text", c=c)


def frame_cite(citations: list[dict]) -> dict:
    return envelope("cite", citations=citations)


def frame_done(conversation_id: str, message_id: str) -> dict:
    return envelope("done", conversation_id=conversation_id, message_id=message_id)


def frame_error(code: str, message: str, retryable: bool) -> dict:
    return envelope("error", code=code, message=message, retryable=retryable)


def frame_heartbeat() -> dict:
    return envelope("heartbeat")


def to_sse(frame: dict) -> str:
    """`data: {json}\n\n` 单行 SSE。ensure_ascii=False 保全中文；default=str 兜底 uuid 等。"""
    body = json.dumps(frame, ensure_ascii=False, default=str)
    return f"data: {body}\n\n"


def serialize_frame(frame: Any) -> str:
    """兼容别名（接受 dict 或已序列化 str）。"""
    return frame if isinstance(frame, str) else to_sse(frame)
