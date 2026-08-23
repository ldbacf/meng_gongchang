"""ChatService — 问答图驱动 + 消息持久化 + SSE v1 投影（O-4.2/O-4.3/O-4.6）。

收敛旧 `src/routers/chat.py` 470 行内联串行管线为**驱动 QAGraph**（S-4.2 三处重复编排合之）。

- `stream_chat(req, user)`：入口（短会话）——确保会话 / 校验 KB 存在 / 落库用户消息 /
  读历史 / 分配 AI message_id；可能 raise 404（会话或 KB 不存在），在 endpoint 内先行。
  返回 `_sse(initial)` async generator（SSE 帧 dict）。
- `_sse(initial)`：`task + asyncio.Queue` 解耦客户端生命周期与图生命周期（A-4.3 断连不丢消息）：
  - 独立 task 跑 `graph.astream_events(initial, config, version='v2')`，事件 → SSE 帧 `put_nowait`；
    断连后丢弃不阻塞图。
  - 心跳独立 task（`frame_heartbeat`），不放图内（C7）。
  - 客户端断开 → 取消心跳 task，**不取消图 task**（图继续到 persist 落库）。
- `_event_to_frame`：`on_custom_event` → 帧（step/text/cite/done）。任意外抛 → `_on_error`
  产 `t:error` + 落库 failed 的 AI 消息（content 不含 `[错误:...]`，A-4.4）。

持久化一律短会话（`get_db_sessionmaker()()`），generator 不持有路由注入的长活 session（T-4.10）。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select

from app.application.checkpoint_registry import config_for, thread_id_for_rag
from app.interface.sse import (
    frame_done,
    frame_error,
    frame_heartbeat,
    frame_cite,
    frame_step,
    frame_text,
)
from src.models import Conversation, KnowledgeBase, Message

_HEARTBEAT_INTERVAL = 10.0  # 秒；长流防网关掐断（A-4.7）
_QUEUE_MAX = 500
_SENTINEL = object()


class ChatService:
    def __init__(self, container):
        self._c = container

    # ── 入口（可能 raise 404，endpoint 内先行）─────────────────

    async def stream_chat(self, req, user) -> AsyncGenerator[dict, None]:
        initial = await self._prepare(req, user)
        return self._sse(initial)

    # ── 准备阶段（短会话）─────────────────────────────────────

    async def _prepare(self, req, user) -> dict:
        conv_id = await self._ensure_conversation(req, user)
        kb = await self._resolve_kb(req.kb_id)
        user_msg_id = str(uuid.uuid4())
        await self._persist_user_message(conv_id, user_msg_id, req.message)
        history = await self._read_history(conv_id, exclude_id=user_msg_id)
        return {
            "message_id": str(uuid.uuid4()),  # AI 消息确定性 id（done 帧/幂等）
            "conversation_id": str(conv_id),
            "user_id": str(user.id),
            "query": req.message,
            "kb": kb,
            "history": history,
        }

    async def _ensure_conversation(self, req, user) -> uuid.UUID:
        async with self._c.get_db_sessionmaker()() as session:
            if req.conversation_id:
                try:
                    conv_id = uuid.UUID(req.conversation_id)
                except ValueError:
                    raise HTTPException(400, "conversation_id 格式无效")
                r = await session.execute(
                    select(Conversation).where(
                        Conversation.id == conv_id, Conversation.user_id == user.id
                    )
                )
                if r.scalar_one_or_none() is None:
                    raise HTTPException(404, "会话不存在")
                return conv_id
            title = req.message[:30] + ("..." if len(req.message) > 30 else "")
            conv = Conversation(user_id=user.id, title=title)
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            return conv.id

    async def _resolve_kb(self, kb_id) -> dict:
        """KB 归属（已确认：所有登录用户可查所有库；kb 不存在→404，无 403）。

        返回 `{kb_id, es_index, milvus_collection, kb_kind}` 或空 dict（未指定 kb）。
        """
        if not kb_id:
            return {
                "kb_id": None, "es_index": None,
                "milvus_collection": None, "kb_kind": "medical_default",
            }
        try:
            kb_uuid = uuid.UUID(kb_id)
        except ValueError:
            raise HTTPException(400, "kb_id 格式无效")
        async with self._c.get_db_sessionmaker()() as session:
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_uuid))
            kb = r.scalar_one_or_none()
            if kb is None:
                raise HTTPException(404, "知识库不存在")
            from app.domain.knowledge_base import resolve_kb_kind

            return {
                "kb_id": str(kb.id),
                "es_index": kb.es_index,
                "milvus_collection": kb.milvus_collection,
                "kb_kind": resolve_kb_kind(kb).value,
            }

    async def _persist_user_message(self, conv_id: uuid.UUID, msg_id: str, content: str) -> None:
        async with self._c.get_db_sessionmaker()() as session:
            msg = Message(
                id=uuid.UUID(msg_id), conversation_id=conv_id, role="user", content=content,
            )
            session.add(msg)
            r = await session.execute(select(Conversation).where(Conversation.id == conv_id))
            conv = r.scalar_one_or_none()
            if conv:
                conv.updated_at = sa_func.now()
            await session.commit()

    async def _read_history(self, conv_id: uuid.UUID, exclude_id: str) -> list[dict]:
        async with self._c.get_db_sessionmaker()() as session:
            r = await session.execute(
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at.asc())
            )
            rows = r.scalars().all()
        return [
            {"role": m.role, "content": m.content}
            for m in rows if str(m.id) != exclude_id
        ]

    # ── SSE 驱动（task + queue 解耦断连）────────────────────────

    def _sse(self, initial: dict) -> AsyncGenerator[dict, None]:
        graph = self._c.get_rag_graph()
        cid = initial["conversation_id"]
        mid = initial["message_id"]
        cfg = config_for(thread_id_for_rag(cid, mid))
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)

        async def _runner() -> None:
            try:
                async for ev in graph.astream_events(initial, config=cfg, version="v2"):
                    frame = self._event_to_frame(ev)
                    if frame is not None:
                        self._put(q, frame)
            except Exception as e:  # 图异常 → error_handler（t:error + 落库 failed）
                await self._on_error(initial, e)
                self._put(q, frame_error("rag_error", str(e), retryable=True))
            finally:
                self._put(q, _SENTINEL)

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                self._put(q, frame_heartbeat())

        graph_task = asyncio.create_task(_runner())
        hb_task = asyncio.create_task(_heartbeat())

        async def _gen():
            try:
                while True:
                    item = await q.get()
                    if item is _SENTINEL:
                        break
                    yield item
            finally:
                hb_task.cancel()
                # 断连：不取消 graph_task，让它继续跑到 persist_message（A-4.3 不丢 AI 消息）

        return _gen()

    @staticmethod
    def _put(q: asyncio.Queue, item) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass  # 断连后满队，丢弃帧不阻塞图上文

    @staticmethod
    def _event_to_frame(ev: dict) -> dict | None:
        """astream_events(version='v2') 的 on_custom_event → SSE 帧。"""
        if ev.get("event") != "on_custom_event":
            return None
        name = ev.get("name")
        data = ev.get("data", {})
        if name == "step":
            return frame_step(
                data.get("k", ""), data.get("s", "done"),
                data.get("elapsed_ms", 0), data.get("metrics", {}),
            )
        if name == "token":
            return frame_text(data.get("c", ""))
        if name == "cite":
            return frame_cite(data.get("citations", []))
        if name == "done":
            return frame_done(data.get("conversation_id", ""), data.get("message_id", ""))
        return None

    async def _on_error(self, initial: dict, exc: Exception) -> None:
        """落库 failed 的 AI 消息（content 空，错误经 t:error 帧，不拼进正文，A-4.4）。"""
        try:
            cid = uuid.UUID(initial["conversation_id"])
            mid = uuid.UUID(initial["message_id"])
            rag_steps = dict(initial.get("rag_steps") or {})
            rag_steps["answer"] = {"status": "failed", "title": "生成回答", "error": str(exc)}
            async with self._c.get_db_sessionmaker()() as session:
                existing = await session.execute(select(Message).where(Message.id == mid))
                ai = existing.scalar_one_or_none()
                if ai is None:
                    ai = Message(
                        id=mid, conversation_id=cid, role="ai",
                        content="", citations=[], rag_steps=rag_steps,
                    )
                    session.add(ai)
                else:
                    ai.rag_steps = rag_steps
                await session.commit()
        except Exception:
            pass  # 错误降级：落库失败不阻断 SSE error 帧
