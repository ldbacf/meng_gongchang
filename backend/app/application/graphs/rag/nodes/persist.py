"""persist — 落库 AI 消息 + citations + rag_steps，产 `t:done`（含 message_id 幂等）。

- **短会话**（`get_db_sessionmaker()()`），不持有路由注入的长活 session（O-4.6 / T-4.10）。
- 幂等：`Message.id = message_id`（确定性，ChatService 入口分配）；已存在则 UPDATE，
  resume/重放不产生重复 AI 消息（A-4.3 幂等）。
- `conversation.updated_at` 刷新。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select

from app.application.graphs.rag.nodes._emit import emit_done
from app.interface.deps import get_container
from src.models import Conversation, Message


async def persist(state: dict) -> dict:
    cid = str(state["conversation_id"])
    mid = str(state["message_id"])
    answer_text = state.get("answer") or ""
    citations = state.get("citations") or []
    rag_steps = state.get("rag_steps") or {}

    cid_uuid = uuid.UUID(cid)
    mid_uuid = uuid.UUID(mid)

    async with get_container().get_db_sessionmaker()() as session:
        existing = await session.execute(select(Message).where(Message.id == mid_uuid))
        ai = existing.scalar_one_or_none()
        if ai is None:
            ai = Message(
                id=mid_uuid, conversation_id=cid_uuid, role="ai",
                content=answer_text, citations=citations, rag_steps=rag_steps,
            )
            session.add(ai)
        else:
            ai.content = answer_text
            ai.citations = citations
            ai.rag_steps = rag_steps

        conv_r = await session.execute(select(Conversation).where(Conversation.id == cid_uuid))
        conv = conv_r.scalar_one_or_none()
        if conv:
            conv.updated_at = sa_func.now()

        await session.commit()

    await emit_done(cid, mid)
    return {"done": True}
