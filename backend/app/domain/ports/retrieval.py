"""检索端口 — 双路召回 + 精排。

应用层的 retrieval / fusion 节点只依赖本协议：换掉 ES/Milvus/rerank 供应商时
不必改图节点。实现见 `app/infrastructure/search.py`（当前用模块函数 + 容器注入，
`domain` 只描述能力，不约束实现形态）。
"""
from __future__ import annotations

from typing import Protocol

from app.domain.retrieval.search_hit import SearchHit


class RetrievalPort(Protocol):
    """双路召回 + 精排能力。"""

    def recall_dual(
        self,
        query: str,
        filters: dict | None = None,
        milvus_top_k: int = 200,
        es_top_k: int = 200,
        es_index: str | None = None,
        milvus_collection: str | None = None,
    ) -> tuple[list[SearchHit], list[SearchHit]]:
        """返回 `(milvus_hits, es_hits)`，**不做融合**（融合是 domain 的 rrf_fusion）。"""
        ...

    def rerank(
        self, query: str, docs: list[SearchHit], top_n: int | None = None
    ) -> list[SearchHit]:
        """精排；失败时应保序返回而非抛错（降级由调用方判定）。"""
        ...
