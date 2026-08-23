"""会话 & 聊天路由 — 会话 CRUD + SSE 流式 RAG（阶段 4：驱动 QAGraph）。

阶段 4 收缩：`chat_stream` 不再内联 470 行串行管线，改经 `ChatService.stream_chat`
驱动 QAGraph（图 = pipeline/编排唯一真相）。SSE 帧由 `interface/sse.py` 投影（v 信封）。
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.interface.deps import get_container
from app.interface.sse import to_sse
from src.auth import get_current_user
from src.db import get_db
from src.models import Conversation, Message, User
from src.schemas import (
    ChatSendRequest,
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


# ── 会话管理 ────────────────────────────────────────────────


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            Conversation.id,
            Conversation.title,
            Conversation.updated_at,
            Conversation.created_at,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50),
    )
    rows = result.all()
    return [
        ConversationResponse(
            id=row.id,
            title=row.title,
            updated_at=row.updated_at,
            created_at=row.created_at,
            message_count=row.message_count,
        )
        for row in rows
    ]


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    req: ConversationCreate = ConversationCreate(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=user.id, title=req.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        updated_at=conv.updated_at,
        created_at=conv.created_at,
        message_count=0,
    )


@router.patch("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: uuid.UUID,
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "会话不存在")
    conv.title = body.title[:50] or "对话"
    conv.updated_at = func.now()
    await db.commit()
    return {"ok": True}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "会话不存在")
    await db.delete(conv)
    await db.commit()
    return {"ok": True}


@router.get(
    "/conversations/{conv_id}/messages", response_model=list[MessageResponse]
)
async def list_messages(
    conv_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "会话不存在")

    q = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )

    if before:
        from datetime import datetime as dt

        try:
            cursor_dt = dt.fromisoformat(before)
            q = q.where(Message.created_at < cursor_dt)
        except ValueError:
            pass

    result = await db.execute(q)
    messages = result.scalars().all()
    return list(reversed(messages))


# ── SSE 流式 RAG（驱动 QAGraph）──────────────────────────────


@router.post("/chat/stream")
async def chat_stream(
    req: ChatSendRequest,
    user: User = Depends(get_current_user),
):
    """SSE 流式 RAG — 驱动 QAGraph，逐帧推送 `{v:1, t:step|text|cite|done|error|heartbeat}`。

    入口（会话/KB 校验 + 落库用户消息）在 `ChatService._prepare` 内先行，
    404/400 在返回 StreamingResponse 前抛出。
    """
    gen = await get_container().get_chat_service().stream_chat(req, user)

    async def _sse():
        async for frame in gen:
            yield to_sse(frame)

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
