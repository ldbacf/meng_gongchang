"""SearchHit 数据契约 — 检索命中（原 `src/search.py` 契约保留）。

哨兵 rank=999999 表示该召回路未命中；四套分数 score_rrf/score_es/score_milvus/score_rerank。
纯 stdlib，零外部依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field

RANK_SENTINEL = 999999


@dataclass
class SearchHit:
    chunk_id: str = ""
    doc_id: str = ""
    level: str = ""
    chunk_type: str = ""
    doi: str = ""
    journal: str = ""
    title_cn: str = ""
    title: str = ""
    section: str = ""
    article_type: str = ""
    heading_stack: list[str] = field(default_factory=list)
    content: str = ""
    html_body: str = ""
    score_rrf: float = 0.0
    score_rerank: float = 0.0
    score_milvus: float = 0.0
    score_es: float = 0.0
    rank_milvus: int = RANK_SENTINEL
    rank_es: int = RANK_SENTINEL

    @property
    def from_milvus(self) -> bool:
        return self.rank_milvus != RANK_SENTINEL

    @property
    def from_es(self) -> bool:
        return self.rank_es != RANK_SENTINEL
