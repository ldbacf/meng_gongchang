"""Milvus collection schema 唯一真相源 — 规范脚本与在线自动建共用。

- 10 字段：chunk_id(PK) / doc_id / doi / level / chunk_type / journal /
  section / article_type / title_cn / embedding[dim]。
- `dim`（EMBEDDING_DIM）与 `nlist`（MILVUS_NLIST）读 Settings，禁止脚本硬编码。
"""
from __future__ import annotations

from pymilvus import CollectionSchema, DataType, FieldSchema

from app.infrastructure.settings import get_settings


def build_milvus_fields(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="chunk_id",    dtype=DataType.VARCHAR, max_length=128, is_primary=True),
        FieldSchema(name="doc_id",      dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="doi",         dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="level",       dtype=DataType.VARCHAR, max_length=4),
        FieldSchema(name="chunk_type",  dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="journal",     dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="section",     dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="article_type", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="title_cn",    dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="embedding",   dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]


def build_milvus_schema(dim: int | None = None, description: str | None = None) -> CollectionSchema:
    settings = get_settings()
    dim = dim or settings.embedding_dim
    return CollectionSchema(
        fields=build_milvus_fields(dim),
        description=description or "PDF chunk 三粒度切分 (L0/L1/L2)",
    )


def build_milvus_index_params(nlist: int | None = None) -> dict:
    settings = get_settings()
    return {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": nlist or settings.milvus_nlist},
    }


# 通用知识库 chunk 的字段长度截断上限（写库前逐字段截断，防止超长拒绝）
FIELD_MAX_LENGTH = {
    "chunk_id": 128, "doc_id": 32, "doi": 128, "level": 4, "chunk_type": 16,
    "journal": 128, "section": 128, "article_type": 128, "title_cn": 512,
}


def truncate_field(value: str, field: str) -> str:
    limit = FIELD_MAX_LENGTH.get(field, 256)
    return value if len(value) <= limit else value[:limit]
