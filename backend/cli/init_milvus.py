"""Milvus Collection 初始化 — 创建 chunks collection（标量 + 向量字段）。

⚠️ 红线：本命令会 **DROP 并重建** `chunks` 集合，清空已入库数据！
只允许在全新环境（无任何数据）使用。判断方法：Milvus `num_entities` 非 0 就绝不能运行。

schema 与在线自动建同源：`app/infrastructure/milvus/schema.py`（dim/nlist 读 Settings）。

用法: python -m cli.init_milvus
"""
from __future__ import annotations

from pymilvus import Collection, connections, utility

from app.infrastructure.milvus.schema import build_milvus_index_params, build_milvus_schema
from app.infrastructure.settings import get_settings
from src.config import MILVUS_COLLECTION, MILVUS_HOST, MILVUS_PORT

COLLECTION_NAME = MILVUS_COLLECTION


def main() -> None:
    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    print(f"[Milvus] 已连接 {MILVUS_HOST}:{MILVUS_PORT}")

    if utility.has_collection(COLLECTION_NAME):
        print(f"[Milvus] 删除已有 collection: {COLLECTION_NAME}")
        utility.drop_collection(COLLECTION_NAME)

    settings = get_settings()
    schema = build_milvus_schema(dim=settings.embedding_dim)
    collection = Collection(name=COLLECTION_NAME, schema=schema)
    print(f"[Milvus] Collection 创建成功: {COLLECTION_NAME}")

    index_params = build_milvus_index_params(nlist=settings.milvus_nlist)
    collection.create_index(field_name="embedding", index_params=index_params)
    print(
        f"[Milvus] 索引创建成功: IVF_FLAT / COSINE / "
        f"nlist={settings.milvus_nlist} / dim={settings.embedding_dim}"
    )
    collection.load()
    print("[Milvus] Collection 已加载")


if __name__ == "__main__":
    main()
