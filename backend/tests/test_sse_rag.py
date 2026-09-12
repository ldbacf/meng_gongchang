"""T-4.3 / T-4.5 / T-4.6 — SSE v1 信封 + metrics 单源 + 降级标记。

- T-4.3：每帧带 `v:1`；step/text/cite/done/error/heartbeat 结构合契约（7.7）。
- T-4.5：intent/retrieval/fusion/answer metrics 由单工厂（build_rag_step）产出，字段一致。
- T-4.6：intent / rerank 失败 → 对应 metrics.degraded=true（A-4.5 可观测，不静默）。
"""
from __future__ import annotations

from app.application.graphs.rag.nodes import fusion, intent
from app.application.graphs.rag.nodes._emit import (
    emit_cite,
    emit_done,
    emit_step,
    emit_text,
)
from app.application.rag.rag_metrics import STEP_TITLES, build_rag_step
from app.domain.rag.intent import IntentResult
from app.domain.retrieval.search_hit import SearchHit
from app.infrastructure.container import AppContainer
from app.interface.deps import set_container
from app.interface.sse import (
    frame_cite,
    frame_done,
    frame_error,
    frame_heartbeat,
    frame_step,
    frame_text,
    to_sse,
)


# ── T-4.3 ──────────────────────────────────────────────────────


def test_sse_envelope_structure():
    # 每帧带 v:1 信封（契约 7.7）
    frames = [
        frame_step("intent", "done", 12, {"coverage": "high"}),
        frame_text("你好"),
        frame_cite([{"idx": "1", "doc_id": "d1", "title": "t", "snippet": "s", "md5": ""}]),
        frame_done("conv-1", "msg-1"),
        frame_error("rag_error", "boom", True),
        frame_heartbeat(),
    ]
    for f in frames:
        assert f["v"] == 1
    assert frames[0]["t"] == "step" and frames[0]["k"] == "intent" and frames[0]["s"] == "done"
    assert frames[0]["elapsed_ms"] == 12 and frames[0]["metrics"] == {"coverage": "high"}
    assert frames[1]["t"] == "text" and frames[1]["c"] == "你好"
    assert frames[2]["t"] == "cite" and frames[2]["citations"][0]["doc_id"] == "d1"
    assert frames[3]["t"] == "done" and frames[3]["message_id"] == "msg-1"
    assert frames[4]["t"] == "error" and frames[4]["retryable"] is True
    assert frames[5]["t"] == "heartbeat"
    # 序列化：data: {json}\n\n，中文不转义
    assert to_sse(frame_text("你好")).startswith("data: {")
    assert "你好" in to_sse(frame_text("你好"))
    # emit_* 发射的自定义事件名 → _event_to_frame 映射（SSE 帧名）
    from app.application.services.chat_service import ChatService

    assert ChatService._event_to_frame({"event": "on_custom_event", "name": "step", "data": {"k": "intent", "s": "done", "elapsed_ms": 1, "metrics": {}}})["t"] == "step"
    assert ChatService._event_to_frame({"event": "on_custom_event", "name": "token", "data": {"c": "x"}})["t"] == "text"
    assert ChatService._event_to_frame({"event": "on_chain_end", "name": "answer", "data": {}}) is None


# ── T-4.5 ──────────────────────────────────────────────────────


def test_metrics_single_source_fields():
    # 四步字段契约定稿（4.2.2），由单工厂产出，无手写字典
    intent_step = build_rag_step("intent", elapsed_ms=1, domain="医学", coverage="high", rewritten_query="q", keywords=["a"], suggestion="")
    assert set(intent_step["metrics"].keys()) == {"domain", "coverage", "rewritten_query", "keywords", "suggestion", "degraded"}

    retr_step = build_rag_step("retrieval", elapsed_ms=2, milvus_hits=3, es_hits=4, after_dedup=5, routing="both")
    assert set(retr_step["metrics"].keys()) == {"milvus_hits", "es_hits", "after_dedup", "routing", "degraded"}

    fusion_step = build_rag_step("fusion", elapsed_ms=3, input_count=5, output_count=4, top_scores=[0.9])
    assert set(fusion_step["metrics"].keys()) == {"input_count", "output_count", "model", "top_scores", "degraded"}
    assert fusion_step["metrics"]["model"] == "Qwen3-Reranker-4B"

    ans_step = build_rag_step("answer", elapsed_ms=4, context_chunks=5, total_tokens=100, total_elapsed_ms=400)
    assert set(ans_step["metrics"].keys()) == {"model", "context_chunks", "total_tokens", "total_elapsed_ms", "degraded"}
    assert ans_step["metrics"]["model"] == "DeepSeek-V4-Pro"

    assert set(STEP_TITLES.keys()) == {"intent", "retrieval", "fusion", "answer"}


# ── T-4.6 ──────────────────────────────────────────────────────


def test_degraded_flag_build_rag_step():
    assert build_rag_step("intent", degraded=True, domain="")["metrics"]["degraded"] is True
    assert build_rag_step("fusion", degraded=True, input_count=1, output_count=1)["metrics"]["degraded"] is True


async def test_intent_degraded_on_fail(monkeypatch):
    from app.infrastructure.settings import Settings

    set_container(AppContainer(settings=Settings(_env_file=None, jwt_secret_key="x", use_query_expansion=False)))

    monkeypatch.setattr("app.infrastructure.adapters.query_intent.analyze_intent", lambda query, last_context="", kb_kind=None: IntentResult())

    out = await intent.intent({
        "query": "高血压怎么治",
        "kb": {"kb_kind": "generic"},
        "history": [],
        "rag_steps": {},
    })
    assert out["rag_steps"]["intent"]["metrics"]["degraded"] is True
    assert out["rewritten_query"] == "高血压怎么治"  # 降级：原 query 直通


async def test_fusion_degraded_on_silent_fail(monkeypatch):
    # rerank 静默失败（全 0 分）→ fusion 判降级、保序返回
    def fake_rerank(query, hits, top_n):
        return list(hits)  # 保序，score_rerank 全 0

    monkeypatch.setattr("app.infrastructure.search.rerank", fake_rerank)

    def _h():
        return SearchHit(chunk_id="c1", doc_id="d1", content="正文", rank_milvus=1, score_rrf=1.0)

    out = await fusion.fusion({
        "query": "q",
        "hits": [_h()],
        "es_hits": [_h()],
        "rag_steps": {},
    })
    assert out["rag_steps"]["fusion"]["metrics"]["degraded"] is True
    assert len(out["reranked"]) == 1  # 保序返回，不中断
