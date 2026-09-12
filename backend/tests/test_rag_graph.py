"""T-4.1 / T-4.2 / T-4.4 / T-4.8 — QAGraph 行为测试。

- 组件：QAGraph（InMemorySaver）+ 真实 PG（persist 落库）；外部适配器（intent/召回/重排/LLM/ES）
  用 monkeypatch 注入 fake，避免真实 DeepSeek / ES / Milvus。
- T-4.1 happy path：节点序列推进；persist 落库 AI 消息 citations+rag_steps；done 带 message_id。
- T-4.2 abort/resume：answer 失败后同 thread_id 续跑，仅重放 answer 段（不整条重来）。
- T-4.4 error frame：answer 持续失败 → runner 产 t:error + 落库 failed（content 空，不含 [错误]）。
- T-4.8 token 不进 checkpoint：checkpoint 状态不含 token 级流式键。
"""
from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.application.checkpoint_registry import config_for, thread_id_for_rag
from app.application.graphs.rag.rag_graph import build_rag_graph
from app.application.services.chat_service import ChatService
from app.domain.rag.intent import IntentResult
from app.domain.retrieval.search_hit import SearchHit
from app.infrastructure.container import AppContainer
from app.interface.deps import set_container
from app.infrastructure.db.models import Conversation, Message, User


def _fact(n: int, seed: str) -> tuple[list[SearchHit], list[SearchHit]]:
    m_hits, e_hits = [], []
    for i in range(n):
        m_hits.append(SearchHit(
            chunk_id=f"{seed}_m{i}", doc_id=f"doc{i}", level="L1",
            title="临床指南", content=f"{seed} 正文{i}", rank_milvus=i + 1,
        ))
        e_hits.append(SearchHit(
            chunk_id=f"{seed}_e{i}", doc_id=f"doc{i}", level="L1",
            title="临床指南", content=f"{seed} 正文{i}", rank_es=i + 1,
        ))
    return m_hits, e_hits


@pytest.fixture
async def rag_env(monkeypatch):
    from app.infrastructure.settings import Settings

    container = AppContainer(
        settings=Settings(
            _env_file=None, jwt_secret_key="pytest-test-secret", use_query_expansion=False,
        ),
        fakes={"rag_graph": build_rag_graph(InMemorySaver())},
    )
    set_container(container)

    async with container.get_db_sessionmaker()() as session:
        user = User(username=f"qt_{uuid.uuid4().hex[:8]}", password_hash="x", role="user")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        conv = Conversation(user_id=user.id, title="测试会话")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        uid, cid = str(user.id), str(conv.id)

    # ── 外部适配器 fake ──
    recall_calls = {"n": 0}

    def fake_recall_dual(query, **kw):
        recall_calls["n"] += 1
        return _fact(3, query[:4])

    def fake_rerank(query, hits, top_n):
        for i, h in enumerate(hits):
            h.score_rerank = 1.0 - i * 0.1
        return hits

    def fake_analyze(query, last_context="", kb_kind=None):
        return IntentResult(domain="医学", coverage="high", rewritten_query=query)

    monkeypatch.setattr("app.infrastructure.search.recall_dual", fake_recall_dual)
    monkeypatch.setattr("app.infrastructure.search.rerank", fake_rerank)
    monkeypatch.setattr("app.infrastructure.adapters.query_intent.analyze_intent", fake_analyze)

    yield container, uid, cid, recall_calls

    async with container.get_db_sessionmaker()() as session:
        from sqlalchemy import delete

        await session.execute(delete(Message).where(Message.conversation_id == uuid.UUID(cid)))
        await session.execute(delete(Conversation).where(Conversation.id == uuid.UUID(cid)))
        await session.execute(delete(User).where(User.username.like("qt_%")))


def _initial(uid: str, cid: str):
    return {
        "message_id": str(uuid.uuid4()),
        "conversation_id": cid,
        "user_id": uid,
        "query": "高血压怎么治",
        # GENERIC：cite 节点跳过 ES L0 回填（避免测试依赖真实 ES）
        "kb": {"kb_id": None, "es_index": "kb_t4", "milvus_collection": "kb_t4", "kb_kind": "generic"},
        "history": [],
    }


async def _run(graph, initial, cfg, answer_tokens):
    """驱动 astream_events(v2)，收集 SSE 帧，返回帧列表。"""
    import app.application.services.chat_service as cs

    frames = []
    async for ev in graph.astream_events(initial, config=cfg, version="v2"):
        f = cs.ChatService._event_to_frame(ev)
        if f:
            frames.append(f)
    return frames


async def test_happy_path(rag_env, monkeypatch):
    container, uid, cid, _ = rag_env

    # LLM 流式 fake
    async def fake_answer_stream(user_prompt, kb_kind):
        yield "高"; yield "血压"; yield "建议"

    monkeypatch.setattr("app.infrastructure.adapters.llm_answer.answer_stream_async", fake_answer_stream)

    graph = container.get_rag_graph()
    initial = _initial(uid, cid)
    mid = initial["message_id"]
    cfg = config_for(thread_id_for_rag(initial["conversation_id"], mid))

    frames = await _run(graph, initial, cfg, None)

    kinds = [f["t"] for f in frames]
    assert "done" in kinds and "cite" in kinds
    step_done = [f for f in frames if f["t"] == "step" and f["s"] == "done"]
    assert {f["k"] for f in step_done} == {"intent", "retrieval", "fusion", "answer"}
    text = "".join(f["c"] for f in frames if f["t"] == "text")
    assert "高血压建议" in text
    done = [f for f in frames if f["t"] == "done"][0]
    assert done["message_id"] == mid

    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(Message).where(Message.id == uuid.UUID(mid)))
        ai = r.scalar_one()
        assert ai.role == "ai"
        assert ai.content == "高血压建议"
        assert ai.citations  # 非空
        assert set((ai.rag_steps or {}).keys()) == {"intent", "retrieval", "fusion", "answer"}


async def test_abort_resume_replays_only_answer(rag_env, monkeypatch):
    container, uid, cid, recall_calls = rag_env

    calls = {"answer": 0}

    async def flaky_answer_stream(user_prompt, kb_kind):
        calls["answer"] += 1
        if calls["answer"] == 1:
            raise RuntimeError("LLM 暂时不可用")
        yield "重放后的回答"

    monkeypatch.setattr("app.infrastructure.adapters.llm_answer.answer_stream_async", flaky_answer_stream)

    graph = container.get_rag_graph()
    initial = _initial(uid, cid)
    cfg = config_for(thread_id_for_rag(initial["conversation_id"], initial["message_id"]))

    with pytest.raises(RuntimeError):
        await graph.ainvoke(initial, cfg)

    # 首跑已到 fusion 前，answer 未完成 → recall 只跑一次
    assert recall_calls["n"] == 1

    # 同 thread 续跑：仅重放 answer 段（recall 不再跑）
    await graph.ainvoke(None, cfg)
    assert recall_calls["n"] == 1       # retrieval 未重跑
    assert calls["answer"] == 2          # answer 重放了一次

    st = await graph.aget_state(cfg)
    assert st.values.get("answer") == "重放后的回答"


async def test_token_not_in_checkpoint(rag_env, monkeypatch):
    container, uid, cid, _ = rag_env

    async def fake_answer_stream(user_prompt, kb_kind):
        for t in ["一", "二", "三"]:
            yield t

    monkeypatch.setattr("app.infrastructure.adapters.llm_answer.answer_stream_async", fake_answer_stream)

    graph = container.get_rag_graph()
    initial = _initial(uid, cid)
    cfg = config_for(thread_id_for_rag(initial["conversation_id"], initial["message_id"]))

    await _run(graph, initial, cfg, None)
    st = await graph.aget_state(cfg)

    # token 级流式内容不进 state：只应有最终 answer（整段），无逐 token / buffer 键
    assert st.values.get("answer") == "一二三"
    assert not any(
        "token" in k.lower() or "buffer" in k.lower() or "stream" in k.lower()
        for k in st.values
    )


async def test_error_frame_and_failed_message(rag_env, monkeypatch):
    container, uid, cid, _ = rag_env

    async def broken_answer_stream(user_prompt, kb_kind):
        raise RuntimeError("生成失败")

    monkeypatch.setattr("app.infrastructure.adapters.llm_answer.answer_stream_async", broken_answer_stream)

    initial = _initial(uid, cid)
    mid = initial["message_id"]

    gen = ChatService(container)._sse(initial)
    frames = [f async for f in gen]

    err = [f for f in frames if f["t"] == "error"]
    assert err and err[0]["code"] == "rag_error" and err[0]["retryable"] is True
    # 正文不含 [错误]（content 为空，经 t:error 帧）
    assert not any("[" in f.get("message", "") or "错误" in f.get("message", "")
                   for f in frames if f["t"] == "error")

    async with container.get_db_sessionmaker()() as session:
        r = await session.execute(select(Message).where(Message.id == uuid.UUID(mid)))
        ai = r.scalar_one()
        assert ai.role == "ai"
        assert "[错误" not in ai.content
        assert (ai.rag_steps or {}).get("answer", {}).get("status") == "failed"
