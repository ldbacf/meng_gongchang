"""RRF（Reciprocal Rank Fusion）融合 — 纯函数，零外部依赖。

自 `src/search.py::_rrf_fusion` 迁入，**保留同 chunk_id 合并 + ES 字段回填语义**：
- 同一 chunk_id 的 milvus/es 两路 rank 合并（score_rrf 累加）。
- ES 命中回填 Milvus 缺的字段（content/html_body/heading_stack/title/title_cn/journal/doi）。
"""
from __future__ import annotations


def rrf_fusion(
    m_hits: list,
    e_hits: list,
    k: int = 20,
    top_k: int = 100,
) -> list:
    """RRF 融合去重，按 score_rrf 降序。"""
    merged: dict[str, object] = {}

    for hit in m_hits:
        cid = hit.chunk_id
        if cid not in merged:
            merged[cid] = hit
        merged[cid].score_rrf += 1.0 / (k + hit.rank_milvus)

    for hit in e_hits:
        cid = hit.chunk_id
        if cid not in merged:
            merged[cid] = hit
        merged[cid].score_es = hit.score_es
        merged[cid].rank_es = hit.rank_es
        merged[cid].score_rrf += 1.0 / (k + hit.rank_es)

        # 从 ES 回填 Milvus 没有的字段
        if hit.content:
            merged[cid].content = hit.content
        if hit.html_body:
            merged[cid].html_body = hit.html_body
        if hit.heading_stack:
            merged[cid].heading_stack = hit.heading_stack
        if hit.title:
            merged[cid].title = hit.title
        if hit.title_cn:
            merged[cid].title_cn = hit.title_cn
        if hit.journal:
            merged[cid].journal = hit.journal
        if hit.doi:
            merged[cid].doi = hit.doi

    sorted_hits = sorted(merged.values(), key=lambda x: x.score_rrf, reverse=True)
    return sorted_hits[:top_k]
