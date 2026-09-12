"""T-5.3 / T-5.4 / T-5.5 — 观测三项（/metrics + JSON 日志 + OTel span）。

全部离线（不连 PG/ES/Milvus/DeepSeek）：metrics 用真实 MetricsRegistry（空指标也会输出
HELP/TYPE 行）；logger 直接测 JsonFormatter；span 用 InMemorySpanExporter + 注入 fake sessionmaker
驱动一次 QAGraph（ChatService._sse）断言节点 span + 外部 retrieval span。
"""
from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.application.graphs.rag.rag_graph import build_rag_graph
from app.application.services.chat_service import ChatService
from app.domain.rag.intent import IntentResult
from app.domain.retrieval.search_hit import SearchHit
from app.infrastructure.container import AppContainer
from app.infrastructure.observability.logger import JsonFormatter
from app.infrastructure.observability.tracing import get_spans, init_tracing
from app.infrastructure.settings import Settings
from app.interface.deps import set_container


# ── T-5.3 ──────────────────────────────────────────────────────


def test_metrics_endpoint():
    set_container(AppContainer())  # 不 start（metrics 不需 PG/模型）
    from app.interface.routers.metrics import router as metrics_router

    app = FastAPI()
    app.include_router(metrics_router)
    r = TestClient(app).get("/metrics")
    assert r.status_code == 200
    body = r.text
    for name in ("graph_node_duration_seconds", "rag_total", "rag_degraded_total",
                 "retrieval_latency_seconds", "rerank_latency_seconds",
                 "llm_latency_seconds", "mineru_latency_seconds",
                 "queue_depth", "quota_remaining", "quota_rejected_total",
                 "llm_error_total", "mineru_error_total"):
        assert name in body, f"missing metric: {name}"


# ── T-5.4 ──────────────────────────────────────────────────────


def test_json_logger_formatter():
    rec = logging.LogRecord(
        "app.test", logging.INFO, "f.py", 1, "hello %s", ("world",), None,
    )
    rec.ctx = {"kb_id": "kb1"}
    line = JsonFormatter().format(rec)
    data = json.loads(line)
    assert data["level"] == "INFO"
    assert data["msg"] == "hello world"
    assert data["logger"] == "app.test"
    assert data["ctx"] == {"kb_id": "kb1"}
    assert "ts" in data


# ── T-5.5 ──────────────────────────────────────────────────────


class _FakeResult:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return []


class _FakeSession:
    async def execute(self, *a, **k):
        return _FakeResult()

    def add(self, *a):
        pass

    async def commit(self):
        pass


class _FakeSessionCtx:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *a):
        return False


class _FakeSessionMaker:
    def __call__(self):
        return _FakeSessionCtx()


def _hit(cid="d1"):
    return SearchHit(chunk_id=cid, doc_id=cid, content="正文", rank_milvus=1, rank_es=1)


async def test_tracing_rag_spans(monkeypatch):
    from app.infrastructure.observability.tracing import InMemorySpanExporter

    init_tracing(exporter=InMemorySpanExporter())

    container = AppContainer(
        settings=Settings(_env_file=None, jwt_secret_key="x", use_query_expansion=False),
        fakes={
            "sessionmaker": _FakeSessionMaker(),
            "rag_graph": build_rag_graph(InMemorySaver()),
        },
    )
    set_container(container)

    monkeypatch.setattr(
        "app.infrastructure.search._get_embed_model",
        lambda: type("M", (), {"embed_query": lambda self, q: [0.1] * 8})(),
    )
    monkeypatch.setattr(
        "app.infrastructure.search._milvus_search", lambda emb, filters=None, **kw: [_hit()]
    )
    monkeypatch.setattr("app.infrastructure.search._es_search", lambda q, filters=None, **kw: [_hit("d2")])
    monkeypatch.setattr(
        "app.infrastructure.search.rerank", lambda q, hits, top_n: hits,
    )
    monkeypatch.setattr(
        "app.infrastructure.adapters.query_intent.analyze_intent", lambda q, last_context="", kb_kind=None: IntentResult(domain="医学", coverage="high", rewritten_query=q),
    )

    async def fake_answer_stream(user_prompt, kb_kind):
        yield "回答"

    monkeypatch.setattr("app.infrastructure.adapters.llm_answer.answer_stream_async", fake_answer_stream)

    initial = {
        "message_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "query": "高血压怎么治",
        "kb": {"kb_id": None, "es_index": "kb_t5", "milvus_collection": "kb_t5", "kb_kind": "generic"},
        "history": [],
    }
    gen = ChatService(container)._sse(initial)
    frames = [f async for f in gen]
    assert any(f["t"] == "done" for f in frames)  # 完整跑完（fake sessionmaker 落库 no-op）

    spans = get_spans()
    names = {s.name for s in spans}
    for node in ("build_context", "intent", "retrieval", "fusion", "cite", "answer", "persist"):
        assert node in names, f"缺图节点 span: {node}"
    assert "retrieval.dual" in names  # 外部调用 span（recall_dual 实测插桩）
