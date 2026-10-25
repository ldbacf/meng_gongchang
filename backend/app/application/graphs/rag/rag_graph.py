"""QAGraph 组装（红线 C3：compile 必挂 checkpointer）。

节点链：
- 常规（检索）：build_context → intent → retrieval → fusion → cite → answer → persist → END
- 直答（库外）：build_context → intent → **direct_answer** → persist → END

`intent` 之后是**条件边**：意图识别判定 `coverage == out_of_domain`（寒暄 / 元问题 /
完全超出语料库）时跳过检索直接作答；其余情况照旧检索。判定见
`app.domain.rag.routing.decide_route`（纯函数，可单测）。

- 每节点自动落 checkpoint（C6 方案①，AsyncPostgresSaver / 测试 InMemorySaver）。
- 降级节点（intent/retrieval/fusion）内部 catch 置 degraded 不中断；answer 失败上抛由
  service error_handler 兜底（产 t:error + 落库 failed）。
- 无节点内 interrupt（QAGraph 单发 + checkpoint 续跑，不需要 sleep 状态机）。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.application.graphs.rag.nodes.answer import answer
from app.application.graphs.rag.nodes.build_context import build_context
from app.application.graphs.rag.nodes.cite import cite
from app.application.graphs.rag.nodes.direct_answer import direct_answer
from app.application.graphs.rag.nodes.fusion import fusion
from app.application.graphs.rag.nodes.intent import intent
from app.application.graphs.rag.nodes.persist import persist
from app.application.graphs.rag.nodes.retrieval import retrieval
from app.application.graphs.rag.state import QaState
from app.domain.rag.routing import decide_after_fusion, decide_route

_NODES = [
    ("build_context", build_context),
    ("intent", intent),
    ("retrieval", retrieval),
    ("fusion", fusion),
    ("cite", cite),
    ("answer", answer),
    ("direct_answer", direct_answer),
    ("persist", persist),
]


def route_after_intent(state: dict) -> str:
    """条件边：intent 之后是回检索还是直接作答。"""
    intent_state = state.get("intent") or {}
    decision = decide_route(
        coverage=intent_state.get("coverage"),
        degraded=bool(intent_state.get("degraded")),
    )
    return decision.target


def _min_evidence_score() -> float:
    """阈值来自配置；配置不可用（极早期 / 单测）时回落 domain 默认值。"""
    from app.domain.rag.routing import MIN_EVIDENCE_SCORE

    try:
        from app.infrastructure.settings import get_settings

        return float(get_settings().rag_min_evidence_score)
    except Exception:
        return MIN_EVIDENCE_SCORE


def route_after_fusion(state: dict) -> str:
    """条件边②：检索完了，证据够不够支撑回答。

    「low 覆盖度」本身**不触发** —— 只看实际检索质量：
    没有任何带正文的片段，或 rerank top1 低于阈值 → 转直答。

    ⚠️ **rerank 降级时一律继续检索**：精排服务挂掉/未配额度时所有分数是 0，
    此时分数不代表相关性，若照常套阈值会把**每一次提问**都判成"证据不足"，
    等于把检索整条链路废掉。fusion 节点已用 `degraded=True` 标记这种情况。
    """
    reranked = state.get("reranked") or []
    has_content = any(getattr(h, "content", "") for h in reranked)

    fusion_metrics = ((state.get("rag_steps") or {}).get("fusion") or {}).get("metrics") or {}
    if fusion_metrics.get("degraded"):
        return "cite"

    top_score = max(
        (float(getattr(h, "score_rerank", 0) or 0) for h in reranked),
        default=0.0,
    )
    decision = decide_after_fusion(
        top_score=top_score,
        has_content=has_content,
        min_score=_min_evidence_score(),
    )
    return decision.target


def build_rag_graph(checkpointer):
    """构建 QAGraph（checkpointer 由容器/测试注入，禁止裸 compile）。"""
    g = StateGraph(QaState)
    for name, fn in _NODES:
        g.add_node(name, fn)
    g.add_edge(START, "build_context")
    g.add_edge("build_context", "intent")
    g.add_conditional_edges(
        "intent",
        route_after_intent,
        {"retrieval": "retrieval", "direct_answer": "direct_answer"},
    )
    g.add_edge("retrieval", "fusion")
    g.add_conditional_edges(
        "fusion",
        route_after_fusion,
        {"cite": "cite", "direct_answer": "direct_answer"},
    )
    g.add_edge("cite", "answer")
    g.add_edge("answer", "persist")
    g.add_edge("direct_answer", "persist")
    g.add_edge("persist", END)
    return g.compile(checkpointer=checkpointer)
