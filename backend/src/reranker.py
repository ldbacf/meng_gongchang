"""
Reranker 封装 — Qwen3-Reranker-4B via 硅基流动 API，LangChain BaseDocumentCompressor 接口。

用法:
    from src.reranker import SiliconFlowReranker

    reranker = SiliconFlowReranker(top_n=20)
    docs = reranker.compress_documents(query, documents)
"""

from __future__ import annotations

from typing import Sequence

import httpx
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document

from src.config import SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_RERANK_MODEL


class SiliconFlowReranker(BaseDocumentCompressor):
    """硅基流动 Qwen3-Reranker，LangChain 兼容的 Document Compressor"""

    model: str = SILICONFLOW_RERANK_MODEL
    top_n: int = 20
    timeout: float = 60.0

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, model: str = "", top_n: int = 20, timeout: float = 60.0):
        super().__init__()
        object.__setattr__(self, "model", model or SILICONFLOW_RERANK_MODEL)
        object.__setattr__(self, "top_n", top_n)
        object.__setattr__(self, "timeout", timeout)

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> list[Document]:
        """
        对文档列表做精排，返回按 relevance_score 降序排列的文档。
        """
        if not documents or not SILICONFLOW_API_KEY:
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
                f"{SILICONFLOW_BASE_URL}/rerank",
                json=payload,
                headers={
                    "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
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
