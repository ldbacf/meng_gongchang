"""IngestionGraph 组装（红线 C3：compile 必挂 checkpointer；C5：RecursionLimit 兜底）。

节点链：poll_parsed →(done) download_unpack → dispatch_index →(index_document 子图) → finalize
条件边：poll_parsed →(pending) pause_wait(interrupt) → poll_parsed；→(timeout/fatal) finalize
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.application.graphs.nodes.dispatch_index import dispatch_index
from app.application.graphs.nodes.download_unpack import download_unpack
from app.application.graphs.nodes.finalize import finalize
from app.application.graphs.nodes.poll_parsed import pause_wait, poll_parsed
from app.application.graphs.state import IngestState


def _route_poll(state: IngestState) -> str:
    if state.get("fatal"):
        return "finalize"
    if state.get("resume_dispatch"):
        return "dispatch"  # resume：跳过 poll/下载，直接派发索引
    if state.get("poll_items"):
        return "download"
    return "pause"


def build_ingest_graph(checkpointer) -> object:
    """构建批级入库图（checkpointer 由容器/测试注入，禁止裸 compile）。"""
    g = StateGraph(IngestState)
    g.add_node("poll_parsed", poll_parsed)
    g.add_node("pause_wait", pause_wait)
    g.add_node("download_unpack", download_unpack)
    g.add_node("dispatch_index", dispatch_index)
    g.add_node("finalize", finalize)

    g.add_edge(START, "poll_parsed")
    g.add_conditional_edges(
        "poll_parsed",
        _route_poll,
        {
            "download": "download_unpack",
            "pause": "pause_wait",
            "finalize": "finalize",
            "dispatch": "dispatch_index",
        },
    )
    g.add_edge("pause_wait", "poll_parsed")  # resume 后继续轮询（poll_count 已 checkpoint）
    g.add_edge("download_unpack", "dispatch_index")
    g.add_edge("dispatch_index", "finalize")
    g.add_edge("finalize", END)

    # recursion_limit 由 checkpoint_registry.config_for 注入（C5 防自环失控）
    return g.compile(checkpointer=checkpointer)
