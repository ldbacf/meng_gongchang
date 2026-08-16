"""CitationBuilder — 引用组装（纯函数，零外部依赖）。

自 `src/routers/chat.py` 内联块提取。**ES 查询（`l0_meta`）留在 src/infrastructure，
builder 只接收结果 dict 入参**（domain 零外部依赖，T-2.8）。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.knowledge_base import KBKind


@dataclass
class Citation:
    id: str
    title: str
    source: str
    snippet: str
    doc_id: str | None = None
    relevance: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "snippet": self.snippet,
            "doc_id": self.doc_id,
            "relevance": self.relevance,
        }


def build_citations(
    hits: list,
    l0_meta: dict | None = None,
    kb_kind: KBKind | None = None,
    max_citations: int = 5,
    snippet_len: int = 200,
) -> list[Citation]:
    """从 reranked hits 构建引用列表（按 doc_id 去重，取前 N 篇不同文献）。

    - GENERIC KB：用 `hit.title`（兜底"未知文档"）。
    - MEDICAL_DEFAULT：用 `hit.title_cn` 兜底 `l0_meta.title_cn`（再兜"未知标题"）；
      source 用 `hit.journal` 兜底 `l0_meta.journal`（再兜"中国全科医学"）。
    """
    l0_meta = l0_meta or {}
    is_generic = kb_kind is KBKind.GENERIC

    citations: list[Citation] = []
    seen_docs: set[str] = set()

    for hit in hits:
        if not hit.content or not hit.doc_id:
            continue
        if hit.doc_id in seen_docs:
            continue
        seen_docs.add(hit.doc_id)
        if len(citations) >= max_citations:
            break

        extra = l0_meta.get(hit.doc_id, {})
        if is_generic:
            title = hit.title or "未知文档"
            journal = ""
        else:
            title = hit.title_cn or extra.get("title_cn") or "未知标题"
            journal = hit.journal or extra.get("journal") or "中国全科医学"
        source = journal or "通用知识库"
        snippet = hit.content[:snippet_len] + (
            "..." if len(hit.content) > snippet_len else ""
        )
        citations.append(Citation(
            id=str(len(citations) + 1),
            title=title,
            source=source,
            snippet=snippet,
            doc_id=str(hit.doc_id),
            relevance=hit.score_rerank,
        ))

    return citations
