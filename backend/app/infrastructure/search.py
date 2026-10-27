"""
检索管线模块 — 双路召回 + RRF 融合 + Rerank 接口（经 AppContainer 取客户端）。

用法:
    from app.infrastructure.search import search, rerank

    results = search("儿童用药政策", top_k=20)
    results = rerank("儿童用药政策", results)
"""

from __future__ import annotations

from collections.abc import Callable

from app.infrastructure.settings import get_settings

# SearchHit 契约统一来自 domain（re-export 兼容 test/ 手动脚本 `from app.infrastructure.search import SearchHit`）
from app.domain.retrieval.search_hit import SearchHit  # noqa: F401


# ═══════════════════════════════════════════════════════════════
# 客户端获取（经 AppContainer，禁止模块级全局单例）
# ═══════════════════════════════════════════════════════════════


def get_es_client():
    """获取 ES 客户端（容器管理生命周期）。替代旧 `_get_es`。"""
    from app.infrastructure.container import get_container
    return get_container().get_es().client


def connect_milvus():
    """连接 Milvus（容器管理生命周期）。替代旧 `_connect_milvus`。"""
    from app.infrastructure.container import get_container
    get_container().get_milvus().connect()


def _get_embed_model():
    """获取 bge-m3 嵌入器（容器唯一 factory/port）。

    remote 模式为 HttpEmbeddingPort（HTTP 调独立服务），local 为 EmbeddingFactory
    （进程内加载）；两者皆实现 embed_query/embed_documents，调用方签名不变。
    """
    from app.infrastructure.container import get_container
    return get_container().get_embedder()


# ═══════════════════════════════════════════════════════════════
# ES 召回
# ═══════════════════════════════════════════════════════════════


def _es_search(
    query: str,
    filters: dict | None = None,
    top_k: int = 200,
    es_index: str | None = None,
    on_batch: Callable[[int, int], None] | None = None,
    batch_size: int = 100,
) -> list[SearchHit]:
    """ES BM25 召回。

    `on_batch(got, total)` 每拉完一批回调一次，用于前端实时计数。
    **为什么分批**：ES 单次 `size=200` 是一次往返，中间没有任何可上报的点；
    拆成 `size=batch_size` + `from` 翻页后，每批回来就能报一次真实进度。
    代价是多几次往返（200 条 → 2 次），在本项目的索引规模下可接受。

    若 `on_batch is None`（老调用方/单测），退化为一次性取回，行为与原来一致。
    """
    es = get_es_client()
    index = es_index or get_settings().es_index

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

    def _body(size: int, frm: int) -> dict:
        return {
            "size": size,
            "from": frm,
            "query": {
                "bool": {
                    "must": must_clauses,
                    "should": should_clauses,
                    "filter": filter_clauses,
                }
            },
            "_source": True,
        }

    def _to_hits(raw_hits, offset: int) -> list[SearchHit]:
        out = []
        for i, hit in enumerate(raw_hits):
            src = hit["_source"]
            out.append(SearchHit(
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
                rank_es=offset + i + 1,
            ))
        return out

    # 老路径：一次取回（无进度需求）
    if on_batch is None:
        resp = es.search(index=index, body=_body(top_k, 0))
        return _to_hits(resp["hits"]["hits"], 0)

    # 分批：先问总数，再按 batch_size 翻页
    first = es.search(index=index, body=_body(min(batch_size, top_k), 0))
    total = min(int(first["hits"]["total"]["value"]), top_k)
    hits = _to_hits(first["hits"]["hits"], 0)
    on_batch(len(hits), total)

    while len(hits) < total:
        want = min(batch_size, total - len(hits))
        resp = es.search(index=index, body=_body(want, len(hits)))
        chunk = _to_hits(resp["hits"]["hits"], len(hits))
        if not chunk:
            break  # 翻页取空：ES 端提前耗尽，避免死循环
        hits.extend(chunk)
        on_batch(len(hits), total)

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
    from app.infrastructure.container import get_container

    mv = get_container().get_milvus()
    mv.connect()

    # 存量 4 字段通用集合无 level/chunk_type/doi/title_cn 字段，需精简 output_fields
    default_collection = get_settings().milvus_collection
    use_full_fields = not (milvus_collection and milvus_collection != default_collection)
    output_fields = None if use_full_fields else ["chunk_id", "doc_id", "title"]

    raw_hits = mv.search(
        milvus_collection or default_collection,
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
# RRF 融合（迁 domain，保留同 chunk_id 合并 + ES 字段回填语义）
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


def recall_dual(
    query: str,
    filters: dict | None = None,
    milvus_top_k: int = 200,
    es_top_k: int = 200,
    es_index: str | None = None,
    milvus_collection: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[list[SearchHit], list[SearchHit]]:
    """双路初召（embed + ES BM25 + Milvus COSINE），返回 `(milvus_hits, es_hits)`，**不做 RRF**。

    供 QAGraph 的 retrieval 节点调用，后续由 fusion 节点 `rrf_fusion` 独立融合
    （保留"embed 独立 + rrf 独立"语义与按步 metric）。短 query（<15 字）重复嵌入增强向量信号。

    `on_progress(stage: dict)` 是**真实进度回调**（不是估算）：
      - `{"stage": "embed",  "milvus": 0, "es": 0}`                    开始向量化
      - `{"stage": "milvus", "milvus": <已召回>, "es": 0}`              向量路完成
      - `{"stage": "es",     "milvus": M, "es": <已召回>, "es_total": T}` ES 每批回来一次
      - `{"stage": "done",   "milvus": M, "es": E, "dedup": D}`          去重完成

    **为什么两路要并行**：原来是串行（先 Milvus 后 ES），前端在 Milvus 跑完的整段时间里
    只能显示"检索中"，没有任何数字可报。改成 ThreadPool 并行后，先到的那一路先上报。
    注意：ES 仍按批翻页（见 `_es_search`），Milvus 单次返回（ANN 不支持翻页语义，
    它的 limit 就是一次 KNN 的结果集）。

    回调在**工作线程**里触发；调用方负责线程安全（节点里用 `asyncio.run_coroutine_threadsafe`）。
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.observability.instrument import tracked_span

    from app.infrastructure.container import get_container

    def _report(**kw) -> None:
        if on_progress is not None:
            try:
                on_progress(kw)
            except Exception:
                pass  # 进度上报绝不能影响检索本身

    with tracked_span(
        "retrieval.dual", latency_metric=get_container().get_metrics().retrieval_latency, backend="dual",
    ):
        model = _get_embed_model()
        embed_query = f"{query} {query}" if len(query) < 15 else query
        _report(stage="embed", milvus=0, es=0)
        q_emb = model.embed_query(embed_query)

        if on_progress is None:
            # 老路径：串行、无回调（保持原有行为与调用开销）
            m_hits = _milvus_search(q_emb, filters=filters, top_k=milvus_top_k, milvus_collection=milvus_collection)
            e_hits = _es_search(query, filters=filters, top_k=es_top_k, es_index=es_index)
            return m_hits, e_hits

        # 新路径：并行两路，各自上报
        #
        # 两路完成先后不定，所以用量化的共享槽位累积，而不是各自只报自己那一半
        # —— 曾写成 `_report(stage="milvus", milvus=M, es=0)`，在 ES 先到的情况下
        # 把已经上port 的 es 计数又抹成 0，前端数字会跳回去。
        progress = {"milvus": 0, "es": 0}

        def _es_batch(got: int, total: int) -> None:
            progress["es"] = got
            _report(
                stage="es",
                milvus=progress["milvus"],
                es=progress["es"],
                es_total=total,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_mv = pool.submit(
                _milvus_search, q_emb,
                filters=filters, top_k=milvus_top_k, milvus_collection=milvus_collection,
            )
            f_es = pool.submit(
                _es_search, query,
                filters=filters, top_k=es_top_k, es_index=es_index, on_batch=_es_batch,
            )

            m_hits = f_mv.result()
            progress["milvus"] = len(m_hits)
            _report(
                stage="milvus",
                milvus=progress["milvus"],
                es=progress["es"],
            )
            e_hits = f_es.result()
            progress["es"] = len(e_hits)

        _report(
            stage="done",
            milvus=progress["milvus"],
            es=progress["es"],
        )
        return m_hits, e_hits


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
    m_hits, e_hits = recall_dual(
        query, filters=filters,
        milvus_top_k=milvus_top_k, es_top_k=es_top_k,
        es_index=es_index, milvus_collection=milvus_collection,
    )

    from app.domain.retrieval.rrf import rrf_fusion

    return rrf_fusion(m_hits, e_hits, top_k=top_k)


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

    from app.infrastructure.container import get_container

    n = top_n if top_n else len(with_content)
    reranker = get_container().get_reranker(top_n=n)

    lc_docs = [
        Document(page_content=d.content, metadata={"hit_idx": i})
        for i, d in enumerate(with_content)
    ]

    from app.infrastructure.observability.instrument import tracked_span

    try:
        with tracked_span("rerank", latency_metric=get_container().get_metrics().rerank_latency):
            ranked = reranker.compress_documents(lc_docs, query)
    except Exception:
        return docs

    # 写回 score_rerank
    for lc_doc in ranked:
        idx = lc_doc.metadata["hit_idx"]
        with_content[idx].score_rerank = lc_doc.metadata.get("relevance_score", 0.0)

    reranked = sorted(with_content, key=lambda x: x.score_rerank, reverse=True)
    return reranked + without_content
