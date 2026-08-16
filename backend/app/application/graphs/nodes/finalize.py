"""finalize 节点 — 批终态判定（以 DB 回读为准，不信任内存 state）。

- 正常路径：批内各 doc 的 task 已由子图/下载节点置 READY/FAILED，本节点只汇总。
- fatal 路径（poll 超时 / MinerU 不可恢复 / 下载失败）：把批内未达终态的 task 置 FAILED，
  写 mineru 步骤 failed。
"""
from __future__ import annotations

from app.application.graphs.nodes._task import load_task, mark_failed
from app.application.graphs.state import IngestState
from src.models import TaskStatus


async def finalize(state: IngestState) -> dict:
    results: dict[str, str] = {}

    # fatal（轮询超时/不可恢复）：批内未终态 doc 一律 FAILED
    if state.get("fatal"):
        err = (state.get("error") or {}).get("message", "批处理失败")
        for md5 in state.get("md5_list") or []:
            task = await load_task(md5)
            if task and task.status not in (TaskStatus.READY.value, TaskStatus.FAILED.value):
                await mark_failed(md5, err)
            results[md5] = task.status if task else "failed"
        return {"doc_results": results}

    # 正常路径：DB 回读终态
    for md5 in state.get("md5_list") or []:
        task = await load_task(md5)
        results[md5] = task.status if task else "failed"

    return {"doc_results": results}
