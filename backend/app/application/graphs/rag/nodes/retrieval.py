"""retrieval — 双路初召（embed + ES BM25 + Milvus COSINE），不做 RRF（交给 fusion）。

- `recall_dual` 返回 `(milvus_hits, es_hits)`；短 query（<15 字）重复嵌入增强（在 adapter 内）。
- 检索异常 → 降级（`degraded=True`，空 hits），继续 fusion（A-4.5 明确低覆盖提示）。
- **实时计数**：`recall_dual` 的 `on_progress` 在工作线程里回调，这里转成带 `metrics`
  的 pending 帧，前端据此显示「已召回 N 篇」。这是真实进度（ES 分批翻页、两路并行），
  不是估算值。

依赖 `domain.ports.retrieval.RetrievalPort`（经 `adapters.ports_impl` 实现），
不在节点里直接 import 具体检索模块。
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.application.graphs.rag.nodes._emit import emit_step
from app.application.rag.rag_metrics import build_rag_step

logger = logging.getLogger(__name__)


async def retrieval(state: dict) -> dict:
    kb = state.get("kb") or {}
    search_query = state.get("rewritten_query") or state["query"]

    from app.infrastructure.adapters.ports_impl import get_search_adapter

    search = get_search_adapter()

    t0 = time.perf_counter()
    await emit_step("retrieval", "pending")

    # ── 进度回调：工作线程 → 事件循环 → SSE 帧 ──
    #
    # `recall_dual` 整个跑在**一个** `asyncio.to_thread` 里（内部再开线程池并行两路），
    # 意味着回调发生时主循环拿不到控制权 —— 用 `call_soon_threadsafe` 排的任务要等
    # `to_thread` 全部返回后才跑，那时进度已经全部完成、只剩最后一帧。
    # 实测就是这样：只收到 embed / milvus / done，中间的 es 分批全被吞掉。
    #
    # 所以改成**先收集采样、返回后按序回放**：
    #   - 工作线程只往 list 里 append（无锁竞争，追加是原子操作）
    #   - `to_thread` 返回后在同一协程里逐条 await emit_step
    # 这样每一帧都落在主循环内，`adispatch_custom_event` 的 contextvar 天然有效，
    # 也彻底绕开了跨线程 Context 的坑。
    live_samples: list[dict] = []
    last_sig = {"v": None}

    def _on_progress(info: dict) -> None:
        sig = (info.get("stage"), info.get("milvus"), info.get("es"))
        if sig == last_sig["v"]:
            return
        last_sig["v"] = sig

        sample = {
            "live": True,
            "stage": info.get("stage", ""),
            "milvus_hits": info.get("milvus", 0),
            "es_hits": info.get("es", 0),
            # 已取回的**原始**条数（两路相加，未去重）。
            # 单独起名而**不是** after_dedup：两路命中必然重叠（同一篇文献两边都会中），
            # 相加后比去重值大（实测 200+200 → 显示 400，真实去重 372）。
            # 前端据此显示「已召回 N 条」，措辞用「条」不用「篇」——这是 chunk 数，
            # 一篇文献可能贡献多条。去重后的准确值要等两路都到齐，由 done 帧给。
            "fetched": info.get("milvus", 0) + info.get("es", 0),
        }
        if info.get("es_total") is not None:
            sample["es_total"] = info["es_total"]
        live_samples.append(sample)

    async def _replay() -> None:
        """把采样按顺序发出去，保证 done 帧一定在它们之后。"""
        for sample in live_samples:
            await emit_step("retrieval", "pending", metrics=sample)

    degraded = False
    m_hits: list = []
    e_hits: list = []
    try:
        m_hits, e_hits = await asyncio.to_thread(
            search.recall_dual, search_query,
            es_index=kb.get("es_index"), milvus_collection=kb.get("milvus_collection"),
            on_progress=_on_progress,
        )
    except TypeError:
        # 端口实现不接受 on_progress（测试里的 fake）：退回无进度调用
        try:
            m_hits, e_hits = await asyncio.to_thread(
                search.recall_dual, search_query,
                es_index=kb.get("es_index"), milvus_collection=kb.get("milvus_collection"),
            )
        except Exception:
            degraded = True
    except Exception:
        degraded = True

    # 采样回放：必须在 emit done 之前，否则前端会看到「done 之后又回到 pending」
    await _replay()

    milvus_count = len(m_hits)
    es_count = len(e_hits)
    after_dedup = len({h.chunk_id for h in list(m_hits) + list(e_hits)})
    routing = (
        "both" if milvus_count > 0 and es_count > 0
        else "milvus_only" if milvus_count > 0
        else "es_only" if es_count > 0
        else "none"
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    step = build_rag_step(
        "retrieval", elapsed_ms=elapsed_ms,
        milvus_hits=milvus_count, es_hits=es_count,
        after_dedup=after_dedup, routing=routing, degraded=degraded,
    )
    await emit_step("retrieval", "done", elapsed_ms=elapsed_ms, metrics=step["metrics"])

    return {
        "hits": m_hits,
        "es_hits": e_hits,
        "rag_steps": {**state.get("rag_steps", {}), "retrieval": step},
    }

# reload probe 032343

# watcher probe 1793042769.8450592

# probe-242f16

# wf-probe
