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
    heading_stack: list[str] = field(default_factory=list)
    content: str = ""
    html_body: str = ""
    score_rrf: float = 0.0
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

    resp = es.search(index=ES_INDEX, body=body)

    hits = []
    for i, hit in enumerate(resp["hits"]["hits"]):
        src = hit["_source"]
        h = SearchHit(
            chunk_id=src.get("chunk_id", ""),
            doc_id=src.get("doc_id", ""),
            level=src.get("level", ""),
            chunk_type=src.get("chunk_type", ""),
            doi=src.get("doi", ""),
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
) -> list[SearchHit]:
    from pymilvus import Collection

    _connect_milvus()
    collection = Collection(MILVUS_COLLECTION)
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

        # 从 ES 回填 content（Milvus 不存）
        if hit.content:
            merged[cid].content = hit.content
        if hit.html_body:
            merged[cid].html_body = hit.html_body
        if hit.heading_stack:
            merged[cid].heading_stack = hit.heading_stack

    sorted_hits = sorted(merged.values(), key=lambda x: x.score_rrf, reverse=True)
    return sorted_hits[:top_k]


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


_EMBED_MODEL = None  # 模块级单例


def _get_embed_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        import os
        # 清除无效 SSL_CERT_FILE 避免 huggingface_hub 加载失败
        if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
            os.environ.pop("SSL_CERT_FILE", None)
        from sentence_transformers import SentenceTransformer
        _EMBED_MODEL = SentenceTransformer("BAAI/bge-m3")
    return _EMBED_MODEL


def search(
    query: str,
    filters: dict | None = None,
    top_k: int = 20,
    milvus_top_k: int = 200,
    es_top_k: int = 200,
) -> list[SearchHit]:
    """
    双路召回 + RRF 融合。

    参数:
        query: 搜索文本
        filters: 过滤条件，如 {"level": "L1", "section": "儿科最新文章合辑"}
        top_k: 最终返回数
        milvus_top_k: Milvus 初召数（翻倍）
        es_top_k: ES 初召数（翻倍）

    返回:
        list[SearchHit]，按 score_rrf 降序
    """
    model = _get_embed_model()
    q_emb = model.encode(query, normalize_embeddings=True).tolist()

    m_hits = _milvus_search(q_emb, filters=filters, top_k=milvus_top_k)
    e_hits = _es_search(query, filters=filters, top_k=es_top_k)

    results = _rrf_fusion(m_hits, e_hits, top_k=top_k)
    return results


def rerank(
    query: str,
    docs: list[SearchHit],
    model=None,
) -> list[SearchHit]:
    """
    精排 — 对 search 输出的结果用 cross-encoder 重排序。

    参数:
        query: 原始查询
        docs: search 返回的结果列表
        model: reranker 模型实例，需有 model.predict([(q,d)]*n) → list[float] 接口
               （如 BAAI/bge-reranker-v2-m3、cross-encoder/ms-marco-MiniLM 等）

    返回:
        按 score_rerank 降序排列
    """
    if model is None:
        # 无 reranker 时保持原序
        return docs

    pairs = [(query, d.content) for d in docs if d.content]
    try:
        scores = model.predict(pairs)
        for i, d in enumerate([d for d in docs if d.content]):
            d.score_rrf = float(scores[i])  # 复用 score_rrf 字段存 rerank 分
    except Exception:
        pass

    return sorted(docs, key=lambda x: x.score_rrf, reverse=True)
