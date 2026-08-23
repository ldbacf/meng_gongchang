"""QAGraph 组装（红线 C3：compile 必挂 checkpointer）。

节点链：build_context → intent → retrieval → fusion → cite → answer → persist → END。
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
from app.application.graphs.rag.nodes.fusion import fusion
from app.application.graphs.rag.nodes.intent import intent
from app.application.graphs.rag.nodes.persist import persist
from app.application.graphs.rag.nodes.retrieval import retrieval
from app.application.graphs.rag.state import QaState

_NODES = [
    ("build_context", build_context),
    ("intent", intent),
    ("retrieval", retrieval),
    ("fusion", fusion),
    ("cite", cite),
    ("answer", answer),
    ("persist", persist),
]


def build_rag_graph(checkpointer):
    """构建 QAGraph（checkpointer 由容器/测试注入，禁止裸 compile）。"""
    g = StateGraph(QaState)
    for name, fn in _NODES:
        g.add_node(name, fn)
    g.add_edge(START, "build_context")
    g.add_edge("build_context", "intent")
    g.add_edge("intent", "retrieval")
    g.add_edge("retrieval", "fusion")
    g.add_edge("fusion", "cite")
    g.add_edge("cite", "answer")
    g.add_edge("answer", "persist")
    g.add_edge("persist", END)
    return g.compile(checkpointer=checkpointer)
