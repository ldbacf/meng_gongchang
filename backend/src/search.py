"""
检索管线模块 — 双路召回 + RRF 融合 + Rerank 接口（阶段 1：经 AppContainer 取客户端）。

用法:
    from src.search import search, rerank

    results = search("儿童用药政策", top_k=20)
    results = rerank("儿童用药政策", results)
"""

from __future__ import annotations

from src.config import ES_INDEX, MILVUS_COLLECTION, USE_QUERY_EXPANSION

# 阶段 2：SearchHit 契约统一来自 domain（re-export 兼容 test/ 手动脚本 `from src.search import SearchHit`）
from app.domain.retrieval.search_hit import SearchHit  # noqa: F401


# ═══════════════════════════════════════════════════════════════
# 客户端获取（经 AppContainer，禁止模块级全局单例）
# ═══════════════════════════════════════════════════════════════


def get_es_client():
    """获取 ES 客户端（容器管理生命周期）。替代旧 `_get_es`。"""
    from app.interface.deps import get_container
    return get_container().get_es().client


def connect_milvus():
    """连接 Milvus（容器管理生命周期）。替代旧 `_connect_milvus`。"""
    from app.interface.deps import get_container
    get_container().get_milvus().connect()


def _get_embed_model():
    """获取 bge-m3 嵌入模型（容器唯一工厂，单例）。"""
    from app.interface.deps import get_container
    return get_container().get_embedder().get_hf_embeddings()


# ═══════════════════════════════════════════════════════════════
# ES 召回
# ═══════════════════════════════════════════════════════════════


def _es_search(
    query: str,
    filters: dict | None = None,
    top_k: int = 200,
    es_index: str | None = None,
) -> list[SearchHit]:
    es = get_es_client()

    must_clauses = [{"match": {"content": query}}]
    should_clauses = [
        {"match": {"title_cn": {"query": query, "boost": 2.0}}},
        {"match": {"keywords_cn": {"query": query, "boost": 1.5}}},
        {"match": {"metadata.title_cn": {"query": query, "boost": 2.0}}},
        {"match": {"metadata.keywords_cn": {"query": query, "boost": 1.5}}},
    ]
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
                "should": should_clauses,
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
    from app.interface.deps import get_container

    mv = get_container().get_milvus()
    mv.connect()

    # 存量 4 字段通用集合无 level/chunk_type/doi/title_cn 字段，需精简 output_fields
    use_full_fields = not (milvus_collection and milvus_collection != MILVUS_COLLECTION)
    output_fields = None if use_full_fields else ["chunk_id", "doc_id", "title"]

    raw_hits = mv.search(
        milvus_collection or MILVUS_COLLECTION,
        embedding,
        filters=filters,
        top_k=top_k,
        output_fields=output_fields,
    )

    hits = []
    for raw in raw_hits:
        h = SearchHit(
            chunk_id=raw["chunk_id"],
            doc_id=raw["doc_id"],
            level=raw.get("level", ""),
            chunk_type=raw.get("chunk_type", ""),
            doi=raw.get("doi", ""),
            title=raw.get("title", ""),
            title_cn=raw.get("title_cn", ""),
            score_milvus=raw["score"],
            rank_milvus=raw["rank"],
        )
        hits.append(h)

    return hits


# ═══════════════════════════════════════════════════════════════
# RRF 融合（阶段 2：迁 domain，保留同 chunk_id 合并 + ES 字段回填语义）
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


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
    """
    model = _get_embed_model()
    # 短 query 重复嵌入以增强向量信号
    embed_query = f"{query} {query}" if len(query) < 15 else query
    q_emb = model.embed_query(embed_query)

    m_hits = _milvus_search(q_emb, filters=filters, top_k=milvus_top_k, milvus_collection=milvus_collection)
    e_hits = _es_search(query, filters=filters, top_k=es_top_k, es_index=es_index)

    from app.domain.retrieval.rrf import rrf_fusion

    results = rrf_fusion(m_hits, e_hits, top_k=top_k)
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

    可通过环境变量 USE_QUERY_EXPANSION=true 启用口语→学术术语扩展。

    返回:
        (list[SearchHit], IntentResult)
    """
    from src.query_intent import analyze_intent, IntentResult

    intent = analyze_intent(query)
    search_query = intent.rewritten_query or query

    if USE_QUERY_EXPANSION:
        from src.query_expansion import expand_query

        expanded = expand_query(query)
        if expanded and expanded != query and len(expanded) > 5:
            search_query = f"{search_query} {expanded}"

    hits = search(search_query, filters=filters, top_k=top_k, milvus_top_k=milvus_top_k, es_top_k=es_top_k)
    return hits, intent


def rerank(
    query: str,
    docs: list[SearchHit],
    top_n: int | None = None,
) -> list[SearchHit]:
    """
    精排 — 调用硅基流动 Qwen3-Reranker API 重排序（经容器工厂）。

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

    from app.interface.deps import get_container

    n = top_n if top_n else len(with_content)
    reranker = get_container().get_reranker(top_n=n)

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
