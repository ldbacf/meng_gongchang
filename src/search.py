"""
检索管线模块 — 双路召回 + RRF 融合 + Rerank 接口

用法:
    from src.search import search, rerank

    results = search("儿童用药政策", top_k=20)
    results = rerank("儿童用药政策", results, model=my_reranker)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import (
    ES_HOST,
    ES_PORT,
    ES_USER,
    ES_PASSWORD,
    ES_INDEX,
    MILVUS_HOST,
    MILVUS_PORT,
    MILVUS_COLLECTION,
)


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
    rank_milvus: int = 999999
    rank_es: int = 999999


# ═══════════════════════════════════════════════════════════════
# 连接池（模块级单例）
# ═══════════════════════════════════════════════════════════════

_ES_CLIENT = None
_MILVUS_CONNECTED = False


def _get_es():
    global _ES_CLIENT
    if _ES_CLIENT is None:
        from elasticsearch import Elasticsearch
        if ES_USER and ES_PASSWORD:
            _ES_CLIENT = Elasticsearch(
                f"http://{ES_USER}:{ES_PASSWORD}@{ES_HOST}:{ES_PORT}",
            )
        else:
            _ES_CLIENT = Elasticsearch(f"http://{ES_HOST}:{ES_PORT}")
    return _ES_CLIENT


def _connect_milvus():
    global _MILVUS_CONNECTED
    if not _MILVUS_CONNECTED:
        from pymilvus import connections
        connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
        _MILVUS_CONNECTED = True


# ═══════════════════════════════════════════════════════════════
# ES 召回
# ═══════════════════════════════════════════════════════════════


def _es_search(
    query: str,
    filters: dict | None = None,
    top_k: int = 200,
    es_index: str | None = None,
) -> list[SearchHit]:
    es = _get_es()

    must_clauses = [{"match": {"content": query}}]
    filter_clauses = []

    if filters:
        for key, val in filters.items():
            if key == "level":
                filter_clauses.append({"terms": {"level": val if isinstance(val, list) else [val]}})
            elif key == "chunk_type":
                filter_clauses.append({"term": {"chunk_type": val}})
            elif key in ("journal", "section", "article_type", "doi"):
                filter_clauses.append({"term": {key: val}})

    body = {
        "size": top_k,
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses,
            }
        },
        "_source": True,
    }

    resp = es.search(index=es_index or ES_INDEX, body=body)

    hits = []
    for i, hit in enumerate(resp["hits"]["hits"]):
        src = hit["_source"]
        h = SearchHit(
            chunk_id=src.get("chunk_id", ""),
            doc_id=src.get("doc_id", ""),
            level=src.get("level", ""),
            chunk_type=src.get("chunk_type", ""),
            doi=src.get("doi", ""),
            journal=src.get("journal", ""),
            title_cn=src.get("title_cn", ""),
            section=src.get("section", ""),
            article_type=src.get("article_type", ""),
            heading_stack=src.get("heading_stack", []),
            content=src.get("content", ""),
            html_body=src.get("html_body", ""),
            score_es=hit["_score"],
            rank_es=i + 1,
        )
        hits.append(h)

    return hits


# ═══════════════════════════════════════════════════════════════
# Milvus 召回
# ═══════════════════════════════════════════════════════════════


def _milvus_search(
    embedding: list[float],
    filters: dict | None = None,
    top_k: int = 200,
    milvus_collection: str | None = None,
) -> list[SearchHit]:
    from pymilvus import Collection

    _connect_milvus()
    collection = Collection(milvus_collection or MILVUS_COLLECTION)
    collection.load()

    # 构建表达式过滤
    expr_parts = []
    if filters:
        for key, val in filters.items():
            if key == "level":
                if isinstance(val, list):
                    parts = [f'{key} == "{v}"' for v in val]
                    expr_parts.append(f"({' || '.join(parts)})")
                else:
                    expr_parts.append(f'{key} == "{val}"')
            elif key in ("chunk_type", "journal", "section", "article_type", "doi"):
                expr_parts.append(f'{key} == "{val}"')

    expr = " && ".join(expr_parts) if expr_parts else None

    results = collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "nprobe": 16},
        limit=top_k,
        expr=expr,
        output_fields=["chunk_id", "doc_id", "title"],
    ) if milvus_collection and milvus_collection != MILVUS_COLLECTION else collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "nprobe": 16},
        limit=top_k,
        expr=expr,
        output_fields=["chunk_id", "doc_id", "level", "chunk_type", "doi", "title_cn"],
    )

    hits = []
    for rank, hit in enumerate(results[0]):
        fields = hit.entity.fields
        h = SearchHit(
            chunk_id=fields.get("chunk_id", ""),
            doc_id=fields.get("doc_id", ""),
            level=fields.get("level", ""),
            chunk_type=fields.get("chunk_type", ""),
            doi=fields.get("doi", ""),
            title=fields.get("title", ""),
            title_cn=fields.get("title_cn", ""),
            score_milvus=hit.score,
            rank_milvus=rank + 1,
        )
        hits.append(h)

    return hits


# ═══════════════════════════════════════════════════════════════
# RRF 融合
# ═══════════════════════════════════════════════════════════════


def _rrf_fusion(
    m_hits: list[SearchHit],
    e_hits: list[SearchHit],
    k: int = 60,
    top_k: int = 100,
) -> list[SearchHit]:
    """RRF 融合去重，按 score_rrf 降序"""
    merged: dict[str, SearchHit] = {}

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


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


_EMBED_MODEL = None


def _get_embed_model() -> "HuggingFaceEmbeddings":
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from src.llm import get_embedding_model
        _EMBED_MODEL = get_embedding_model()
    return _EMBED_MODEL


def search(
    query: str,
    filters: dict | None = None,
    top_k: int = 20,
    milvus_top_k: int = 200,
    es_top_k: int = 200,
    es_index: str | None = None,
    milvus_collection: str | None = None,
) -> list[SearchHit]:
    """
    双路召回 + RRF 融合。

    参数:
        query: 搜索文本
        filters: 过滤条件
        top_k: 最终返回数
        milvus_top_k: Milvus 初召数
        es_top_k: ES 初召数
        es_index: ES 索引名，默认用 config.ES_INDEX
        milvus_collection: Milvus 集合名，默认用 config.MILVUS_COLLECTION
        es_top_k: ES 初召数（翻倍）

    返回:
        list[SearchHit]，按 score_rrf 降序
    """
    model = _get_embed_model()
    q_emb = model.embed_query(query)

    m_hits = _milvus_search(q_emb, filters=filters, top_k=milvus_top_k, milvus_collection=milvus_collection)
    e_hits = _es_search(query, filters=filters, top_k=es_top_k, es_index=es_index)

    results = _rrf_fusion(m_hits, e_hits, top_k=top_k)
    return results


def search_with_intent(
    query: str,
    filters: dict | None = None,
    top_k: int = 20,
    milvus_top_k: int = 200,
    es_top_k: int = 200,
) -> tuple[list[SearchHit], "IntentResult"]:
    """
    意图识别 + 双路召回 + RRF 融合。

    先调用 DeepSeek-V4-Flash 分析 query 意图并重写，
    再用重写后的 query 做检索，最终返回 (hits, intent)。
    意图识别失败时降级为原始 query 直搜。

    返回:
        (list[SearchHit], IntentResult)
    """
    from src.query_intent import analyze_intent, IntentResult

    intent = analyze_intent(query)
    search_query = intent.rewritten_query or query

    hits = search(search_query, filters=filters, top_k=top_k, milvus_top_k=milvus_top_k, es_top_k=es_top_k)
    return hits, intent


def rerank(
    query: str,
    docs: list[SearchHit],
    top_n: int | None = None,
) -> list[SearchHit]:
    """
    精排 — 调用硅基流动 Qwen3-Reranker API 重排序。

    参数:
        query: 原始查询
        docs: search 返回的结果列表
        top_n: 返回前 N 条，默认全部返回

    返回:
        按 score_rerank 降序排列，无 content 的 chunk 保持原序排在末尾
    """
    if not docs:
        return docs

    with_content = [d for d in docs if d.content]
    without_content = [d for d in docs if not d.content]

    if not with_content:
        return docs

    from langchain_core.documents import Document

    from src.reranker import SiliconFlowReranker

    n = top_n if top_n else len(with_content)
    reranker = SiliconFlowReranker(top_n=n)

    lc_docs = [
        Document(page_content=d.content, metadata={"hit_idx": i})
        for i, d in enumerate(with_content)
    ]

    try:
        ranked = reranker.compress_documents(lc_docs, query)
    except Exception:
        return docs

    # 写回 score_rerank
    for lc_doc in ranked:
        idx = lc_doc.metadata["hit_idx"]
        with_content[idx].score_rerank = lc_doc.metadata.get("relevance_score", 0.0)

    reranked = sorted(with_content, key=lambda x: x.score_rerank, reverse=True)
    return reranked + without_content


def search_and_answer(
    query: str,
    filters: dict | None = None,
    top_k: int = 10,
    stream: bool = False,
) -> "AnswerResult | Generator[str, None, None]":
    """
    一键式：意图识别 → 双路检索 → RRF 融合 → Rerank → LLM 回答。

    参数:
        query: 用户查询
        filters: 过滤条件
        top_k: 召回 top-K
        stream: 是否流式输出

    返回:
        stream=False → AnswerResult
        stream=True  → Generator[str, None, None]
    """
    hits, intent = search_with_intent(query, filters=filters, top_k=top_k)
    reranked = rerank(query, hits, top_n=5 if not stream else 10)

    from src.llm_answer import answer

    return answer(
        query=query,
        hits=reranked,
        intent=intent,
        top_n=5,
        stream=stream,
    )
