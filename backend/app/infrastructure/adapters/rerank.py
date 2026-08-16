"""Rerank 适配器 — Qwen3-Reranker-4B via 硅基流动 API（LangChain Document Compressor）。

从旧 `src/reranker.py` 迁移（读 Settings 而非模块级常量），实例由 AppContainer 持有。
"""
from __future__ import annotations

from typing import Sequence

import httpx
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document

from app.infrastructure.settings import Settings, get_settings


class SiliconFlowReranker(BaseDocumentCompressor):
    """硅基流动 Qwen3-Reranker，LangChain 兼容的 Document Compressor"""

    model: str = ""
    top_n: int = 20
    timeout: float = 60.0
    _api_key: str = ""
    _base_url: str = ""

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self,
        model: str = "",
        top_n: int = 20,
        timeout: float = 60.0,
        settings: Settings | None = None,
    ):
        super().__init__()
        s = settings or get_settings()
        object.__setattr__(self, "model", model or s.siliconflow_rerank_model)
        object.__setattr__(self, "top_n", top_n)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "_api_key", s.siliconflow_api_key)
        object.__setattr__(self, "_base_url", s.siliconflow_base_url)

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> list[Document]:
        """
        对文档列表做精排，返回按 relevance_score 降序排列的文档。
        """
        if not documents or not self._api_key:
            return list(documents)

        texts = [d.page_content for d in documents]
        if not any(texts):
            return list(documents)

        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "return_documents": False,
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/rerank",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return list(documents)

        results = data.get("results", [])
        ranked = []
        for item in results:
            idx = item["index"]
            if idx < len(documents):
                doc = documents[idx]
                doc.metadata["relevance_score"] = item["relevance_score"]
                ranked.append(doc)

        return ranked[: self.top_n] if self.top_n else ranked


def get_reranker(top_n: int = 20, settings: Settings | None = None) -> SiliconFlowReranker:
    """Rerank 工厂 — 容器持有实例。"""
    return SiliconFlowReranker(top_n=top_n, settings=settings)
