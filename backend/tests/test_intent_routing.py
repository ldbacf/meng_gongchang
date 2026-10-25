"""意图路由：什么时候跳过检索直接作答。

背景：原图是直线 `intent → retrieval → fusion → cite → answer`，
意图识别产出的 `coverage` 没有任何节点消费 —— 于是"你好"也会跑完整检索，
最后返回"未找到相关文献信息，无法回答。"。

本文件锁住三件事：
1. 判定规则（out_of_domain 直答，其余检索；降级保守检索）
2. 图里真的有条件边，且直答分支不经过 retrieval
3. 直答节点不产生引用、只写 intent+answer 两步
"""
from __future__ import annotations

import inspect

import pytest

from app.application.graphs.rag import rag_graph as graph_mod
from app.application.graphs.rag.nodes import direct_answer as da_mod
from app.domain.rag.routing import DIRECT_COVERAGES, decide_route


# ── 判定规则 ───────────────────────────────────────────────


@pytest.mark.parametrize("coverage", ["high", "medium", "low"])
def test_kb_coverages_use_retrieval(coverage):
    d = decide_route(coverage=coverage)
    assert d.use_retrieval is True
    assert d.target == "retrieval"


def test_out_of_domain_skips_retrieval():
    d = decide_route(coverage="out_of_domain")
    assert d.use_retrieval is False
    assert d.target == "direct_answer"
    assert d.reason == "coverage=out_of_domain"


def test_coverage_normalized():
    assert decide_route(coverage="  OUT_OF_DOMAIN  ").use_retrieval is False


@pytest.mark.parametrize("coverage", [None, "", "unknown", "weird"])
def test_unknown_coverage_falls_back_to_retrieval(coverage):
    """意图识别失败/给出意外值时保守走检索，不改变原有行为。"""
    assert decide_route(coverage=coverage).use_retrieval is True


def test_degraded_always_retrieves():
    """降级时 coverage 不可信 —— 宁可多检一次，也不能把医学问题当寒暄。"""
    d = decide_route(coverage="out_of_domain", degraded=True)
    assert d.use_retrieval is True
    assert d.reason == "intent_degraded"


def test_direct_coverages_constant():
    assert DIRECT_COVERAGES == {"out_of_domain"}


# ── 图结构 ─────────────────────────────────────────────────


def test_route_after_intent_reads_state():
    assert graph_mod.route_after_intent(
        {"intent": {"coverage": "out_of_domain", "degraded": False}}
    ) == "direct_answer"
    assert graph_mod.route_after_intent(
        {"intent": {"coverage": "high", "degraded": False}}
    ) == "retrieval"
    # 缺 intent（极端情况）→ 检索
    assert graph_mod.route_after_intent({}) == "retrieval"


def test_graph_has_conditional_edge_from_intent():
    """compile 后的图里，intent 的出边应是条件边（带分支映射），不是普通边。"""
    from langgraph.checkpoint.memory import InMemorySaver

    compiled = graph_mod.build_rag_graph(InMemorySaver())
    drawable = compiled.get_graph()
    # 存在 intent → direct_answer 的边，说明分支真的接上了
    edges = {(e.source, e.target) for e in drawable.edges}
    assert ("intent", "direct_answer") in edges
    assert ("intent", "retrieval") in edges


def test_direct_answer_reaches_persist_without_retrieval():
    from langgraph.checkpoint.memory import InMemorySaver

    drawable = graph_mod.build_rag_graph(InMemorySaver()).get_graph()
    edges = {(e.source, e.target) for e in drawable.edges}
    assert ("direct_answer", "persist") in edges
    # 直答分支不能再串回检索链
    assert ("direct_answer", "retrieval") not in edges
    assert ("direct_answer", "fusion") not in edges


# ── 直答节点 ───────────────────────────────────────────────


def test_direct_answer_uses_direct_prompt():
    src = inspect.getsource(da_mod.direct_answer)
    assert "DIRECT_SYSTEM_PROMPT" in src
    assert "system_prompt=" in src, "必须覆盖默认的「只用文献回答」提示词"


def test_direct_answer_emits_no_citations():
    src = inspect.getsource(da_mod.direct_answer)
    assert '"citations": []' in src


def test_direct_answer_marks_route():
    """answer 步 metrics 带 route=direct，便于统计多少提问没走检索。"""
    src = inspect.getsource(da_mod.direct_answer)
    assert "route=reason" in src


def test_answer_metrics_has_route_field():
    from app.application.rag.rag_metrics import build_rag_step

    metrics = build_rag_step("answer").get("metrics") or {}
    assert metrics.get("route") == "retrieval", "检索路径的默认 route 应是 retrieval"

# ── fusion 之后：证据不足转直答 ─────────────────────────────


def test_low_score_goes_direct():
    """top1 低于阈值 → 直答（而不是拿无关片段硬答）。"""
    from app.domain.rag.routing import decide_after_fusion

    d = decide_after_fusion(top_score=0.08, has_content=True)
    assert d.use_retrieval is False
    assert d.target == "direct_answer"
    assert d.reason.startswith("low_score:")


def test_score_above_threshold_continues():
    from app.domain.rag.routing import decide_after_fusion

    d = decide_after_fusion(top_score=0.53, has_content=True)
    assert d.use_retrieval is True
    assert d.target == "cite"


def test_no_content_goes_direct():
    from app.domain.rag.routing import decide_after_fusion

    d = decide_after_fusion(top_score=0.9, has_content=False)
    assert d.target == "direct_answer"
    assert d.reason == "no_content"


def test_threshold_boundary():
    from app.domain.rag.routing import decide_after_fusion

    assert decide_after_fusion(top_score=0.249, has_content=True).target == "direct_answer"
    assert decide_after_fusion(top_score=0.251, has_content=True).target == "cite"


def test_threshold_configurable():
    from app.domain.rag.routing import decide_after_fusion

    # 阈值调高到 0.6 后，0.53 的也算证据不足
    d = decide_after_fusion(top_score=0.53, has_content=True, min_score=0.6)
    assert d.target == "direct_answer"


def test_route_after_fusion_reads_reranked():
    """条件边直接从 state.reranked 取最高分与是否有正文。"""
    from app.application.graphs.rag import rag_graph

    class Hit:
        def __init__(self, score, content="x"):
            self.score_rerank = score
            self.content = content

    assert rag_graph.route_after_fusion({"reranked": [Hit(0.9)]}) == "cite"
    assert rag_graph.route_after_fusion({"reranked": [Hit(0.05)]}) == "direct_answer"
    assert rag_graph.route_after_fusion({"reranked": [Hit(0.9, content="")]}) == "direct_answer"
    assert rag_graph.route_after_fusion({"reranked": []}) == "direct_answer"


def test_graph_has_conditional_edge_from_fusion():
    from langgraph.checkpoint.memory import InMemorySaver

    edges = {(e.source, e.target) for e in graph_mod.build_rag_graph(InMemorySaver()).get_graph().edges}
    assert ("fusion", "cite") in edges
    assert ("fusion", "direct_answer") in edges


# ── 直答原因与声明 ─────────────────────────────────────────


def test_resolve_reason_out_of_domain():
    assert da_mod.resolve_reason({"rag_steps": {"intent": {}}}) == "out_of_domain"


def test_resolve_reason_no_content():
    state = {"rag_steps": {"retrieval": {}}, "reranked": [type("H", (), {"content": ""})()]}
    assert da_mod.resolve_reason(state) == "no_content"


def test_resolve_reason_low_evidence():
    state = {"rag_steps": {"retrieval": {}}, "reranked": [type("H", (), {"content": "x"})()]}
    assert da_mod.resolve_reason(state) == "low_evidence"


def test_low_evidence_has_server_side_disclaimer():
    """声明由服务端追加，不赌模型是否照做。"""
    assert "未引用本知识库文献" in da_mod.DISCLAIMERS["low_evidence"]
    assert "未引用本知识库文献" in da_mod.DISCLAIMERS["no_content"]
    assert da_mod.DISCLAIMERS["out_of_domain"] == ""


def test_low_evidence_uses_different_prompt():
    src = inspect.getsource(da_mod.direct_answer)
    assert "LOW_EVIDENCE_SYSTEM_PROMPT" in src


def test_rerank_degraded_always_continues():
    """精排降级时分数不可信 —— 若照常套阈值，每次提问都会转直答，检索被废掉。"""
    from app.application.graphs.rag import rag_graph

    class Hit:
        score_rerank = 0.0
        content = "有正文但没分数"

    state = {
        "reranked": [Hit()],
        "rag_steps": {"fusion": {"metrics": {"degraded": True}}},
    }
    assert rag_graph.route_after_fusion(state) == "cite"
