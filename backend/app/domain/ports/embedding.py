"""Embedding 端口抽象 — 阶段 1 EmbeddingFactory 实现之。"""
from __future__ import annotations

from typing import Protocol


class EmbeddingPort(Protocol):
    """文本嵌入端口。"""

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
