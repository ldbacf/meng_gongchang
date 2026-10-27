"""检索实时计数：`on_progress` 契约 + 分批翻页 + 两路并行。

背景：前端要显示「已召回 N 篇」，但原来 `_es_search` 是单次 `size=200` 一次性取回，
`recall_dual` 又是串行（先 Milvus 后 ES），整段没有任何可上报的点，只能编假数字。
改为 ES 分批翻页 + 两路并行后，每个真实阶段都能上报。

这里守住三件事：
1. 不传 `on_progress` 时行为与原来完全一致（老调用方/单测不受影响）
2. 传了之后，回调序列覆盖 embed → milvus → es → （节点补 done）
3. ES 翻页能取满，且不会因为空页死循环
"""
from __future__ import annotations

import pytest

from app.domain.retrieval.search_hit import SearchHit
from app.infrastructure import search as search_mod


class _FakeES:
    """模拟 ES：按 from/size 切片返回，hits.total 固定。"""

    def __init__(self, total: int, batch_max: int | None = None):
        self.total = total
        self.batch_max = batch_max
        self.calls: list[tuple[int, int]] = []

    def search(self, index: str, body: dict):
        size = body["size"]
        frm = body.get("from", 0)
        self.calls.append((frm, size))
        # 模拟「后端每页最多给 batch_max 条」的截断
        eff = min(size, self.batch_max) if self.batch_max is not None else size
        end = min(frm + eff, self.total)
        rows = [
            {"_source": {"chunk_id": f"c{i}", "doc_id": f"d{i}", "level": "L1"},
             "_score": 1.0 - i * 0.001}
            for i in range(frm, end)
        ]
        return {"hits": {"total": {"value": self.total}, "hits": rows}}


def _patch_es(monkeypatch, fake: _FakeES) -> None:
    monkeypatch.setattr(search_mod, "get_es_client", lambda: fake)


def test_es_search_without_callback_is_single_request(monkeypatch):
    """不传 on_batch → 仍然一次取回，行为与改造前一致。"""
    fake = _FakeES(total=150)
    _patch_es(monkeypatch, fake)

    hits = search_mod._es_search("高血压", top_k=200, es_index="idx")

    assert len(hits) == 150
    assert len(fake.calls) == 1, f"应只发一次请求，实际 {fake.calls}"
    assert fake.calls[0] == (0, 200)


def test_es_search_pages_and_reports_real_counts(monkeypatch):
    """传 on_batch → 分批翻页，每次上报的是**真实已取条数**。"""
    fake = _FakeES(total=250)
    _patch_es(monkeypatch, fake)

    reports: list[tuple[int, int]] = []
    hits = search_mod._es_search(
        "高血压", top_k=200, es_index="idx",
        on_batch=lambda got, total: reports.append((got, total)),
        batch_size=100,
    )

    assert len(hits) == 200, "应取满 top_k"
    # 250 条候选，但 top_k=200 → total 上限是 200
    assert reports == [(100, 200), (200, 200)], reports
    assert len(fake.calls) == 2


def test_es_search_stops_on_empty_page(monkeypatch):
    """ES 实际返回少于 total（分片未就绪等）时不能死循环。"""
    fake = _FakeES(total=250, batch_max=80)
    _patch_es(monkeypatch, fake)

    hits = search_mod._es_search(
        "高血压", top_k=200, es_index="idx",
        on_batch=lambda got, total: None,
        batch_size=100,
    )

    assert len(hits) == 200
    assert len(fake.calls) < 10, f"翻页次数异常：{fake.calls}"


def test_es_search_reports_monotonic_counts(monkeypatch):
    """上报的已取条数必须单调递增（前端据此做数字跳动，倒退会闪）。"""
    fake = _FakeES(total=180)
    _patch_es(monkeypatch, fake)

    got_seq: list[int] = []
    search_mod._es_search(
        "高血压", top_k=200, es_index="idx",
        on_batch=lambda got, total: got_seq.append(got),
        batch_size=50,
    )

    assert got_seq == sorted(got_seq), got_seq
    assert got_seq[-1] == 180


# ── recall_dual 的进度契约 ──────────────────────────────────────


def test_recall_dual_reports_stages(monkeypatch):
    """回调应覆盖 embed → milvus → es，且带真实计数。"""
    monkeypatch.setattr(search_mod, "_get_embed_model", lambda: type(
        "M", (), {"embed_query": staticmethod(lambda q: [0.1, 0.2])}
    )())

    monkeypatch.setattr(
        search_mod, "_milvus_search",
        lambda emb, **kw: [
            SearchHit(chunk_id="m1", doc_id="d1", level="L1", title="", content=""),
            SearchHit(chunk_id="m2", doc_id="d2", level="L1", title="", content=""),
        ],
    )
    monkeypatch.setattr(
        search_mod, "_es_search",
        lambda q, **kw: [
            SearchHit(chunk_id="e1", doc_id="d3", level="L1", title="", content=""),
        ],
    )

    stages: list[dict] = []
    m, e = search_mod.recall_dual("高血压", on_progress=stages.append)

    assert len(m) == 2 and len(e) == 1
    names = [s["stage"] for s in stages]
    assert "embed" in names
    assert "milvus" in names
    mv = next(s for s in stages if s["stage"] == "milvus")
    assert mv["milvus"] == 2


def test_recall_dual_without_callback_unchanged(monkeypatch):
    """不传 on_progress → 走老路径（串行、无回调），返回结果一致。"""
    monkeypatch.setattr(search_mod, "_get_embed_model", lambda: type(
        "M", (), {"embed_query": staticmethod(lambda q: [0.1])}
    )())
    monkeypatch.setattr(
        search_mod, "_milvus_search",
        lambda emb, **kw: [SearchHit(chunk_id="m1", doc_id="d", level="L1", title="", content="")],
    )
    monkeypatch.setattr(search_mod, "_es_search", lambda q, **kw: [])

    m, e = search_mod.recall_dual("高血压")
    assert len(m) == 1 and e == []


def test_progress_callback_exception_does_not_break_search(monkeypatch):
    """回调抛错绝不能拖垮检索本身。"""
    monkeypatch.setattr(search_mod, "_get_embed_model", lambda: type(
        "M", (), {"embed_query": staticmethod(lambda q: [0.1])}
    )())
    monkeypatch.setattr(
        search_mod, "_milvus_search",
        lambda emb, **kw: [SearchHit(chunk_id="m1", doc_id="d", level="L1", title="", content="")],
    )
    monkeypatch.setattr(search_mod, "_es_search", lambda q, **kw: [])

    def boom(_info):
        raise RuntimeError("前端断连")

    m, _ = search_mod.recall_dual("高血压", on_progress=boom)
    assert len(m) == 1, "回调异常不应影响召回结果"

# ── 节点层：采样回放必须真的发帧 ────────────────────────────────
#
# 这一条守的是一个**极隐蔽的坑**：进度回调发生在 recall_dual 的工作线程里，
# 但整个 recall_dual 跑在单个 asyncio.to_thread 内，主循环要等它整体返回才拿回
# 控制权。最初用 call_soon_threadsafe / run_coroutine_threadsafe 投递，
# 结果任务全都排在 to_thread 结束之后才跑 —— 前端只收到最后一帧，
# 中间所有进度凭空消失，而且不报错（协程被 GC，只剩 RuntimeWarning）。
#
# 现在改成「工作线程只 append 采样，返回后按序 await emit_step」。
# 本测试断言采样数 ≥ 3 且顺序单调，防止有人改回跨线程派发。


@pytest.mark.asyncio
async def test_retrieval_node_emits_live_frames_in_graph_context(monkeypatch):
    """在真实图上下文里跑 retrieval，必须收到多帧带 live 计数的 pending。"""
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import InMemorySaver
    from typing import TypedDict

    import app.application.graphs.rag.nodes.retrieval as retrieval_mod

    class _State(TypedDict, total=False):
        query: str
        kb: dict
        hits: list
        es_hits: list
        rag_steps: dict

    # 造一个会上报 4 次进度的 fake（模拟 embed → milvus → es 两批）
    class _FakeSearch:
        def recall_dual(self, query, **kw):
            cb = kw.get("on_progress")
            assert cb is not None, "节点必须传 on_progress"
            cb({"stage": "embed", "milvus": 0, "es": 0})
            cb({"stage": "milvus", "milvus": 8, "es": 0})
            cb({"stage": "es", "milvus": 8, "es": 5, "es_total": 10})
            cb({"stage": "es", "milvus": 8, "es": 10, "es_total": 10})
            return (
                [SearchHit(chunk_id=f"m{i}", doc_id="d", level="L1", title="", content="") for i in range(8)],
                [SearchHit(chunk_id=f"e{i}", doc_id="d", level="L1", title="", content="") for i in range(10)],
            )

    monkeypatch.setattr(
        "app.infrastructure.adapters.ports_impl.get_search_adapter",
        lambda: _FakeSearch(),
    )

    g = StateGraph(_State)
    g.add_node("retrieval", retrieval_mod.retrieval)
    g.add_edge(START, "retrieval")
    g.add_edge("retrieval", END)
    app = g.compile(checkpointer=InMemorySaver())

    frames = []
    async for ev in app.astream_events(
        {"query": "高血压", "kb": {"es_index": "x", "milvus_collection": "y"}},
        config={"configurable": {"thread_id": "prog-test"}},
        version="v2",
    ):
        if ev.get("event") == "on_custom_event" and ev.get("name") == "step":
            frames.append(ev["data"])

    live = [f for f in frames if (f.get("metrics") or {}).get("live")]
    assert len(live) >= 4, f"应收到至少 4 帧实时进度，实际 {len(live)}: {frames}"

    # es 计数必须单调递增（前端数字跳动，倒退会闪）
    es_seq = [(f["metrics"] or {}).get("es_hits") for f in live]
    assert es_seq == sorted(es_seq), f"es_hits 应单调递增: {es_seq}"

    # done 必须在所有 live 帧之后
    done_idx = next(i for i, f in enumerate(frames) if f.get("s") == "done")
    last_live_idx = max(i for i, f in enumerate(frames) if (f.get("metrics") or {}).get("live"))
    assert last_live_idx < done_idx, "done 帧不能早于实时进度帧"
