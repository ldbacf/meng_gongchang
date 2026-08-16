"""通用知识库索引管线 — Chunk → Embed → ES + Milvus 写入（阶段 1：经 AppContainer）。

- ES/Milvus schema 与规范脚本同源（`app/infrastructure/es/es_mappings.py`、
  `app/infrastructure/milvus/schema.py`），杜绝双轨。
- Milvus 按 chunk_id **先删后插**（幂等，图重跑/重索引安全）。
"""
from pathlib import Path

from app.infrastructure.es.es_mappings import ES_SETTINGS, build_generic_kb_mapping


def read_parsed_markdown(md5: str) -> str:
    """从 MinIO parsed-data/{md5}/ 读取 full.md"""
    from src.minio_client import read_parsed_markdown as _read

    return _read(md5)


def es_bulk_write(
    es_index: str,
    chunks: list[dict],
) -> int:
    """写入 ES 指定索引，不存在自动创建（在线自动建与 init_es 同源 mapping）。"""
    from app.interface.deps import get_container

    es = get_container().get_es().client

    if not es.indices.exists(index=es_index):
        es.indices.create(
            index=es_index,
            body={
                "settings": ES_SETTINGS,
                "mappings": build_generic_kb_mapping(),
            },
        )

    from elasticsearch.helpers import bulk

    actions = [
        {
            "_index": es_index,
            "_id": c["chunk_id"],
            "_source": {k: v for k, v in c.items() if k != "vector"},
        }
        for c in chunks
    ]
    success, _ = bulk(es, actions, refresh=True)
    return success


def milvus_insert(collection_name: str, chunks: list[dict]) -> int:
    """写入 Milvus 指定 collection（不存在自动创建，按 chunk_id 幂等 upsert）。"""
    from app.interface.deps import get_container

    mv = get_container().get_milvus()
    col = mv.ensure_collection(collection_name)
    return mv.upsert_batch(col, chunks)


def process_document(
    md5: str,
    filename: str,
    es_index: str,
    milvus_collection: str,
    on_step=None,
) -> int:
    """
    完整索引管线: markdown → chunk → embed → ES + Milvus.

    on_step(step_name: str, status: str, **kwargs) — 每步回调，用于更新 DB
    返回写入的 chunk 数。
    """
    from src.chunker import (
        FullMdParser, HeadingStack,
        _assemble_l0_chunk_generic,
        _assemble_l1_chunks,
        _assemble_l2_table_chunks,
        build_table_dict, scan_paragraphs,
    )

    markdown = read_parsed_markdown(md5)
    parser = FullMdParser(markdown)
    elements = parser.parse()

    title = Path(filename).stem

    def _step(step: str, status: str, **kwargs):
        if on_step:
            on_step(step, status, **kwargs)

    _step("chunking", "running")

    # L0
    l0 = _assemble_l0_chunk_generic(md5, title, elements)
    # L1
    l1s = _assemble_l1_chunks(md5, "", elements, HeadingStack())
    # L2
    tables = build_table_dict(elements)
    scan_paragraphs(elements, HeadingStack(), tables)
    l2s = _assemble_l2_table_chunks(
        doc_id=md5, doi="", md5=md5, title_cn=title, tables=tables,
    )

    all_chunks = [l0] + l1s + l2s
    _step("chunking", "done", chunk_count=len(all_chunks))

    # Embed
    _step("embedding", "running")
    from app.interface.deps import get_container

    model = get_container().get_embedder().get_hf_embeddings()
    for c in all_chunks:
        c["vector"] = model.embed_query(c["content"])
    _step("embedding", "done")

    # Write ES
    _step("es_write", "running", target_index=es_index)
    n_es = es_bulk_write(es_index, all_chunks)
    _step("es_write", "done", target_index=es_index, count=n_es)

    # Write Milvus
    _step("milvus", "running", target_collection=milvus_collection)
    n_mv = milvus_insert(milvus_collection, all_chunks)
    _step("milvus", "done", target_collection=milvus_collection, count=n_mv)

    return len(all_chunks)
