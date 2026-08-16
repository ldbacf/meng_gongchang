"""
Milvus Collection 初始化 — 一键创建 chunks collection（标量 + 向量字段）。

⚠️ 红线：本脚本会 **DROP 并重建** `chunks` 集合，清空已入库数据！
只允许在全新环境（无任何数据）使用。判断方法：Milvus `num_entities` 非 0 就绝不能运行。

schema 与在线自动建同源：`app/infrastructure/milvus/schema.py`（dim/nlist 读 Settings）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymilvus import Collection, connections, utility

from app.infrastructure.milvus.schema import build_milvus_index_params, build_milvus_schema
from app.infrastructure.settings import get_settings
from src.config import MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION

COLLECTION_NAME = MILVUS_COLLECTION


def main():
    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    print(f"[Milvus] 已连接 {MILVUS_HOST}:{MILVUS_PORT}")

    if utility.has_collection(COLLECTION_NAME):
        print(f"[Milvus] 删除已有 collection: {COLLECTION_NAME}")
        utility.drop_collection(COLLECTION_NAME)

    schema = build_milvus_schema()
    collection = Collection(name=COLLECTION_NAME, schema=schema)
    print(f"[Milvus] Collection 创建成功: {COLLECTION_NAME}")

    settings = get_settings()
    index_params = build_milvus_index_params(nlist=settings.milvus_nlist)
    collection.create_index(field_name="embedding", index_params=index_params)
    print(
        f"[Milvus] 索引创建成功: IVF_FLAT / COSINE / "
        f"nlist={settings.milvus_nlist} / dim={settings.embedding_dim}"
    )

    collection.load()
    print(f"[Milvus] Collection 已加载")


if __name__ == "__main__":
    main()
