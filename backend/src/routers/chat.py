"""会话 & 聊天路由 — 会话 CRUD + SSE 流式 RAG"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.db import get_db
from src.models import Conversation, KnowledgeBase, Message, User
from src.schemas import (
    ChatSendRequest,
    CitationSchema,
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _sl(data: dict) -> str:
    """单行 SSE: data: {json}\n\n"""
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


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


# ── SSE 流式 RAG ────────────────────────────────────────────


@router.post("/chat/stream")
async def chat_stream(
    req: ChatSendRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式 RAG 回答 — 逐步推送管线进度 + 回答 token"""

    # 获取或创建会话
    conv_id: uuid.UUID
    if req.conversation_id:
        try:
            conv_id = uuid.UUID(req.conversation_id)
        except ValueError:
            raise HTTPException(400, "conversation_id 格式无效")
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user.id
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise HTTPException(404, "会话不存在")
    else:
        title = req.message[:30] + ("..." if len(req.message) > 30 else "")
        conv = Conversation(user_id=user.id, title=title)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = conv.id

    # 保存用户消息
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # 更新会话时间
    conv.updated_at = func.now()
    await db.commit()

    async def event_generator():
        import time

        from src.llm_answer import answer
        from src.query_intent import analyze_intent, IntentResult
        from src.search import rerank, search

        message_id = str(uuid.uuid4())
        full_answer_parts: list[str] = []
        rag_steps: dict = {}
        t0 = time.perf_counter()

        # ── Fetch history for multi-turn context ──
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc()),
        )
        all_msgs = result.scalars().all()
        prev_msgs = [m for m in all_msgs if m.id != user_msg.id]

        # History list for answer (last 20 messages = 10 turns)
        history = [
            {"role": m.role, "content": m.content}
            for m in prev_msgs[-20:]
        ]

        # Context for intent recognition (last 4 messages = 2 turns)
        recent = prev_msgs[-4:]
        last_context = ""
        if recent:
            lines = []
            for m in recent:
                role_label = "用户" if m.role == "user" else "AI"
                lines.append(f"{role_label}：{m.content[:300]}")
            last_context = "\n".join(lines)

        # Lookup KB for indexing/search targets
        es_idx = None
        mv_col = None
        is_generic_kb = False
        if req.kb_id:
            kb_result = await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == req.kb_id)
            )
            kb = kb_result.scalar_one_or_none()
            if kb:
                es_idx = kb.es_index
                mv_col = kb.milvus_collection
                is_generic_kb = kb.slug != "zhong_guo_quan_ke"

        # Step 1: 意图识别
        t1 = time.perf_counter()
        yield _sl({"t":"step","k":"intent","s":"pending","title":"意图识别"})
        intent = await asyncio.to_thread(analyze_intent, req.message, last_context, is_generic_kb)
        t1_end = time.perf_counter()
        yield _sl({
            "t":"step","k":"intent","s":"done","title":"意图识别",
            "elapsed_ms": round((t1_end - t1) * 1000),
            "metrics": {
                "domain": intent.domain or "通用",
                "coverage": intent.coverage or "unknown",
                "rewritten_query": intent.rewritten_query or req.message,
                "keywords": intent.keywords or [],
                "suggestion": intent.suggestion or "",
            },
        })
        rag_steps["intent"] = {
            "status": "completed", "title": "意图识别",
            "elapsed_ms": round((t1_end - t1) * 1000),
            "metrics": {
                "domain": intent.domain or "通用",
                "coverage": intent.coverage or "unknown",
                "rewritten_query": intent.rewritten_query or req.message,
                "keywords": intent.keywords or [],
                "suggestion": intent.suggestion or "",
            },
        }

        # Step 2: 混合检索
        t2 = time.perf_counter()
        yield _sl({"t":"step","k":"retrieval","s":"pending","title":"混合检索"})
        search_query = intent.rewritten_query or req.message
        hits = await asyncio.to_thread(
            search, search_query, None, 20, 200, 200,
            es_index=es_idx, milvus_collection=mv_col,
        )
        t2_end = time.perf_counter()
        milvus_count = sum(1 for h in hits if h.rank_milvus != 999999)
        es_count = sum(1 for h in hits if h.rank_es != 999999)
        routing = "both" if milvus_count > 0 and es_count > 0 else "milvus_only" if milvus_count > 0 else "es_only"
        milvus_docs = [h for h in hits if h.rank_milvus != 999999][:3]
        es_docs = [h for h in hits if h.rank_es != 999999][:3]
        overlap = milvus_count + es_count - len(hits)
        yield _sl({
            "t":"step","k":"retrieval","s":"done","title":"混合检索",
            "elapsed_ms": round((t2_end - t2) * 1000),
            "metrics": {
                "milvus_hits": milvus_count, "es_hits": es_count,
                "after_dedup": len(hits), "routing": routing,
                "milvus_top_docs": [{"title": h.title or h.title_cn or "未知文献", "score": round(h.score_milvus, 3)} for h in milvus_docs],
                "es_top_docs": [{"title": h.title or h.title_cn or "未知文献", "score": round(h.score_es, 3)} for h in es_docs],
                "overlap": overlap,
            },
        })
        rag_steps["retrieval"] = {
            "status": "completed", "title": "混合检索",
            "elapsed_ms": round((t2_end - t2) * 1000),
            "metrics": {
                "milvus_hits": milvus_count, "es_hits": es_count,
                "after_dedup": len(hits), "routing": routing,
                "milvus_top_docs": [{"title": h.title or h.title_cn or "未知文献", "score": round(h.score_milvus, 3)} for h in milvus_docs],
                "es_top_docs": [{"title": h.title or h.title_cn or "未知文献", "score": round(h.score_es, 3)} for h in es_docs],
                "overlap": overlap,
            },
        }

        # Step 3: 融合重排
        t3 = time.perf_counter()
        yield _sl({"t":"step","k":"fusion","s":"pending","title":"融合重排"})
        reranked = await asyncio.to_thread(rerank, req.message, hits, 5)
        t3_end = time.perf_counter()
        top_scores = [round(h.score_rerank, 3) for h in reranked[:5] if h.score_rerank > 0]
        yield _sl({
            "t":"step","k":"fusion","s":"done","title":"融合重排",
            "elapsed_ms": round((t3_end - t3) * 1000),
            "metrics": {
                "input_count": len(hits), "output_count": len(reranked),
                "model": "Qwen3-Reranker-4B", "top_scores": top_scores,
            },
        })
        rag_steps["fusion"] = {
            "status": "completed", "title": "融合重排",
            "elapsed_ms": round((t3_end - t3) * 1000),
            "metrics": {
                "input_count": len(hits), "output_count": len(reranked),
                "model": "Qwen3-Reranker-4B", "top_scores": top_scores,
            },
        }

        # Step 4: 生成回答
        t4 = time.perf_counter()
        yield _sl({"t":"step","k":"answer","s":"pending","title":"生成回答","elapsed_ms":0,"summary":"正在检索文献并生成回答..."})
        await asyncio.sleep(0)  # flush pending event before sync streaming loop

        stream_gen = answer(req.message, reranked, history=history, intent=intent, top_n=5, stream=True, is_generic=is_generic_kb)
        char_count = 0
        batch = ""
        for token in stream_gen:
            if isinstance(token, str):
                full_answer_parts.append(token)
                char_count += len(token)
                batch += token
                if len(batch) >= 20 or any(c in token for c in ("。", "！", "？", "\n", " ")):
                    yield _sl({"t":"text","c":batch})
                    batch = ""
                if char_count % 50 < len(token) and char_count > 0:
                    now = time.perf_counter()
                    yield _sl({"t":"step","k":"answer","s":"pending","title":"生成回答",
                               "elapsed_ms": round((now - t4) * 1000),
                               "summary": f"已生成 {char_count} 字符..."})
        if batch:
            yield _sl({"t":"text","c":batch})

        answer_text = "".join(full_answer_parts)
        t4_end = time.perf_counter()
        total_elapsed = round((t4_end - t0) * 1000)
        yield _sl({
            "t":"step","k":"answer","s":"done","title":"生成回答",
            "elapsed_ms": round((t4_end - t4) * 1000),
            "metrics": {
                "model": "DeepSeek-V4-Pro",
                "context_chunks": min(5, len(reranked)),
                "total_tokens": len(answer_text),
                "total_elapsed_ms": total_elapsed,
            },
        })
        rag_steps["answer"] = {
            "status": "completed","title": "生成回答",
            "elapsed_ms": round((t4_end - t4) * 1000),
            "metrics": {
                "model": "DeepSeek-V4-Pro",
                "context_chunks": min(5, len(reranked)),
                "total_tokens": len(answer_text),
                "total_elapsed_ms": total_elapsed,
            },
        }

        # Citations — 按 doc_id 去重，取前 5 篇不同文献
        l0_meta = {} if is_generic_kb else _fetch_l0_meta(reranked)
        citations = []
        seen_docs: set[str] = set()
        for hit in reranked:
            if not hit.content or not hit.doc_id:
                continue
            if hit.doc_id in seen_docs:
                continue
            seen_docs.add(hit.doc_id)
            if len(citations) >= 5:
                break

            extra = l0_meta.get(hit.doc_id, {}) if hit.doc_id else {}
            if is_generic_kb:
                title = hit.title or "未知文档"
                journal = ""
            else:
                title = hit.title_cn or extra.get("title_cn") or "未知标题"
                journal = hit.journal or extra.get("journal") or "中国全科医学"
            source = journal or "通用知识库"
            idx = len(citations) + 1
            c = CitationSchema(
                id=str(idx), title=title, source=source,
                snippet=hit.content[:200] + ("..." if len(hit.content) > 200 else ""),
                doc_id=str(hit.doc_id),
                relevance=hit.score_rerank,
            )
            citations.append(c)
            yield _sl({"t":"cite", **c.model_dump()})

        # 保存 AI 消息
        ai_msg = Message(
            id=uuid.UUID(message_id), conversation_id=conv_id,
            role="ai", content=answer_text,
            citations=[c.model_dump() for c in citations],
            rag_steps=rag_steps,
        )
        db.add(ai_msg)
        await db.commit()

        yield _sl({"t":"done", "conversation_id": str(conv_id), "message_id": message_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _fetch_l0_meta(hits: list) -> dict[str, dict]:
    """批量查询 ES L0 chunk 回填 title_cn / journal / md5"""
    from src.search import _get_es

    doc_ids = sorted({h.doc_id for h in hits if h.doc_id and not h.title_cn})
    if not doc_ids:
        return {}

    try:
        es = _get_es()
        resp = es.search(
            index="chunks",
            body={
                "size": len(doc_ids),
                "query": {
                    "bool": {
                        "must": [
                            {"terms": {"doc_id": doc_ids}},
                            {"term": {"level": "L0"}},
                        ]
                    }
                },
                "_source": ["doc_id", "title_cn", "journal", "md5"],
            },
        )
        result: dict[str, dict] = {}
        for hit in resp.get("hits", {}).get("hits", []):
            src = hit["_source"]
            did = src.get("doc_id", "")
            result[did] = {
                "title_cn": src.get("title_cn", ""),
                "journal": src.get("journal", ""),
                "md5": src.get("md5", ""),
            }
        return result
    except Exception:
        return {}
