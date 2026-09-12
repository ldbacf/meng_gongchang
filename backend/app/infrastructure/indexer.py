"""通用知识库索引管线 — Chunk → Embed → ES + Milvus 写入（经 AppContainer）。

- ES/Milvus schema 与规范脚本同源（`app/infrastructure/es/es_mappings.py`、
  `app/infrastructure/milvus/schema.py`），杜绝双轨。
- Milvus 按 chunk_id **先删后插**（幂等，图重跑/重索引安全）。
"""
from app.infrastructure.es.es_mappings import ES_SETTINGS, build_generic_kb_mapping


def read_parsed_markdown(md5: str) -> str:
    """从 MinIO parsed-data/{md5}/ 读取 full.md（经容器 MinIO 适配器）。"""
    from app.interface.deps import get_container

    return get_container().get_minio().read_parsed_markdown(md5)


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


