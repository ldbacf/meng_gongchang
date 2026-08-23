"""checkpoint thread_id 分配（崩溃续跑 / retry 的确定性键）。

- 批图：`thread_id = batch:{batch_id}`。
- index_document 子图：`thread_id = batch:{batch_id}:doc:{md5}`（继承父图命名空间，C10）。
thread_id 必须**确定性稳定**——它就是崩溃续跑和 checkpoint retry 的定位键。
"""
from __future__ import annotations


def thread_id_for_batch(batch_id: str) -> str:
    return f"batch:{batch_id}"


def thread_id_for_doc(batch_id: str, md5: str) -> str:
    return f"batch:{batch_id}:doc:{md5}"


def thread_id_for_rag(conversation_id: str, message_id: str) -> str:
    """QAGraph 线程键（D3：message 级，确定性 —— 崩溃续跑/SSE 断连幂等的定位键）。"""
    return f"rag:{conversation_id}:{message_id}"


def config_for(thread_id: str) -> dict:
    """graph.ainvoke 的 RunnableConfig（recursion_limit 兜底，C5 防自环失控）。"""
    return {"configurable": {"thread_id": thread_id, "recursion_limit": 1000}}
