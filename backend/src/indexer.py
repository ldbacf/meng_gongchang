"""通用知识库索引管线 — Chunk → Embed → ES + Milvus 写入"""

from pathlib import Path

from src.config import MINIO_PARSED_BUCKET
from src.minio_client import get_minio


def read_parsed_markdown(md5: str) -> str:
    """从 MinIO parsed-data/{md5}/ 读取 full.md"""
    client = get_minio()
    obj = client.get_object(MINIO_PARSED_BUCKET, f"{md5}/full.md")
    return obj.read().decode("utf-8")


def es_bulk_write(
    es_index: str,
    chunks: list[dict],
) -> int:
    """写入 ES 指定索引，不存在自动创建 mapping"""
    from src.search import _get_es

    es = _get_es()

    if not es.indices.exists(index=es_index):
        es.indices.create(index=es_index, body={
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "level": {"type": "keyword"},
                    "chunk_type": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "heading_stack": {"type": "keyword"},
                    "heading_depth": {"type": "integer"},
                }
            }
        })

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
    """写入 Milvus 指定 collection，不存在自动创建"""
    from pymilvus import (
        Collection, CollectionSchema, DataType, FieldSchema,
        connections, utility,
    )
    from src.search import _connect_milvus

    _connect_milvus()

    # 检查已有 collection 维度是否匹配
    if utility.has_collection(collection_name):
        existing = Collection(collection_name)
        need_drop = False
        for f in existing.schema.fields:
            if f.name == "embedding" and hasattr(f, "params"):
                if f.params.get("dim") != 1024:
                    need_drop = True
                break
        if need_drop:
            existing.release()
            utility.drop_collection(collection_name)

    if utility.has_collection(collection_name):
        col = Collection(collection_name)
    else:
        schema = CollectionSchema([
            FieldSchema("chunk_id", DataType.VARCHAR, max_length=256, is_primary=True),
            FieldSchema("doc_id", DataType.VARCHAR, max_length=128),
            FieldSchema("title", DataType.VARCHAR, max_length=256),
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=1024),
        ], description="Generic KB collection")
        col = Collection(collection_name, schema)
        col.create_index(
            "embedding",
            {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 1024}},
        )

    col.load()
    ids = [c["chunk_id"] for c in chunks if c.get("vector")]
    docs = [c["doc_id"] for c in chunks if c.get("vector")]
    titles = [c.get("title", "") for c in chunks if c.get("vector")]
    vecs = [c["vector"] for c in chunks if c.get("vector")]

    if ids:
        col.insert([ids, docs, titles, vecs])
        col.flush()
    return len(ids)


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
    from src.llm import get_embedding_model
    model = get_embedding_model()
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
