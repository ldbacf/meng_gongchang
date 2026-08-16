"""dispatch_index 节点 — 逐 doc 启动/续跑 index_document 子图（C10：子图 thread 继承父命名空间）。

- 子图 thread_id = `batch:{batch_id}:doc:{md5}`（确定性，崩溃续跑/retry 的键）。
- 循环开头查 `task.status == READY`（DB 为准）**跳过已完成 doc**——END 线程 + 非空 input
  会让子图整体重跑（幂等但不必要，A-3.2"不重复"语义靠此保）。
- 子图返回最终 state：fatal → doc_results[md5]="failed"。
"""
from __future__ import annotations

from app.application.checkpoint_registry import config_for, thread_id_for_doc
from app.application.graphs.nodes._task import load_task
from app.application.graphs.state import IngestState
from src.models import TaskStatus


async def dispatch_index(state: IngestState) -> dict:
    from app.interface.deps import get_container

    container = get_container()
    subgraph = container.get_index_subgraph()
    batch_id = state["batch_id"]

    results: dict[str, str] = {}
    # resume 模式（跨 KB 复制/retry）无 parsed_md5s，直接按 md5_list 派发
    for md5 in state.get("parsed_md5s") or state.get("md5_list") or []:
        task = await load_task(md5)
        if task is None:
            results[md5] = "failed"
            continue
        if task.status == TaskStatus.READY.value:
            results[md5] = "ready"  # 已完成（幂等跳过）
            continue

        final = await subgraph.ainvoke(
            {"batch_id": batch_id, "md5": md5},
            config_for(thread_id_for_doc(batch_id, md5)),
        )
        results[md5] = "failed" if final.get("fatal") else "ready"

    return {"doc_results": results}
