"""
Milvus Collection 初始化 — 一键创建 chunks collection（标量 + 向量字段）

Milvus 只存 chunk_id + 标量过滤字段 + embedding，不存 content/html_body。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymilvus import (
    CollectionSchema,
    Collection,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from src.config import MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION

COLLECTION_NAME = MILVUS_COLLECTION
DIM = 1024


def main():
    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    print(f"[Milvus] 已连接 {MILVUS_HOST}:{MILVUS_PORT}")

    if utility.has_collection(COLLECTION_NAME):
        print(f"[Milvus] 删除已有 collection: {COLLECTION_NAME}")
        utility.drop_collection(COLLECTION_NAME)

    fields = [
        FieldSchema(name="chunk_id",    dtype=DataType.VARCHAR, max_length=128, is_primary=True),
        FieldSchema(name="doc_id",      dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="doi",         dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="level",       dtype=DataType.VARCHAR, max_length=4),
        FieldSchema(name="chunk_type",  dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="journal",     dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="section",     dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="article_type", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="title_cn",    dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="embedding",   dtype=DataType.FLOAT_VECTOR, dim=DIM),
    ]

    schema = CollectionSchema(
        fields=fields,
        description="PDF chunk 三粒度切分 (L0/L1/L2)",
    )
    collection = Collection(name=COLLECTION_NAME, schema=schema)
    print(f"[Milvus] Collection 创建成功: {COLLECTION_NAME}")

    index_params = {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    print(f"[Milvus] 索引创建成功: IVF_FLAT / COSINE / nlist=128")

    collection.load()
    print(f"[Milvus] Collection 已加载")


if __name__ == "__main__":
    main()
