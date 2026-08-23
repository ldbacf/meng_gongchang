"""cite — 引用构建 + L0 回填（domain CitationBuilder）。

- GENERIC：命中 `hit.title`（兜底"未知文档"）；MEDICAL_DEFAULT：`hit.title_cn` 兜底 L0 回填。
- 产 `t:cite`（契约 4.2.2，`citations:[{idx,doc_id,title,snippet,md5}]`）；
  落库/状态用 `CitationSchema` 形状（`c.to_dict()`，与旧前端 MessageResponse.citations 一致）。
"""
from __future__ import annotations

from app.application.graphs.rag.nodes._common import fetch_l0_meta
from app.application.graphs.rag.nodes._emit import emit_cite
from app.domain.knowledge_base import KBKind
from app.domain.retrieval.citation import build_citations


async def cite(state: dict) -> dict:
    reranked = state.get("reranked") or []
    kb = state.get("kb") or {}
    kb_kind = KBKind(kb.get("kb_kind", "medical_default"))

    l0_meta = {} if kb_kind is KBKind.GENERIC else fetch_l0_meta(reranked)
    citations = build_citations(reranked, l0_meta=l0_meta, kb_kind=kb_kind)

    # SSE 帧契约（4.2.2）：idx/doc_id/title/snippet/md5
    frame = [
        {
            "idx": c.id,
            "doc_id": c.doc_id,
            "title": c.title,
            "snippet": c.snippet,
            "md5": (l0_meta.get(str(c.doc_id), {}) or {}).get("md5", ""),
        }
        for c in citations
    ]
    await emit_cite(frame)

    # 落库/状态：CitationSchema 形状（id/title/source/snippet/doc_id/relevance）
    return {"citations": [c.to_dict() for c in citations]}
