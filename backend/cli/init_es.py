"""Elasticsearch 索引初始化 — 创建 chunks 索引（IK 分词 + 完整 mapping）。

⚠️ 红线：本命令会 **DROP 并重建** `chunks` 索引，清空已入库数据！
只允许在全新环境（无任何数据）使用。判断方法：先查
`curl localhost:9200/chunks/_count`，非 0 就绝不能运行。

用法: python -m cli.init_es
"""
from __future__ import annotations

from elasticsearch import Elasticsearch

from app.infrastructure.es.es_mappings import ES_MAPPINGS, ES_SETTINGS
from src.config import ES_HOST, ES_INDEX, ES_PASSWORD, ES_PORT, ES_USER

INDEX_NAME = ES_INDEX


def _get_es_client() -> Elasticsearch:
    kwargs = {"request_timeout": 30}
    if ES_USER and ES_PASSWORD:
        return Elasticsearch(f"http://{ES_USER}:{ES_PASSWORD}@{ES_HOST}:{ES_PORT}", **kwargs)
    return Elasticsearch(f"http://{ES_HOST}:{ES_PORT}", **kwargs)


def main() -> None:
    es = _get_es_client()
    if es.indices.exists(index=INDEX_NAME):
        print(f"[ES] 删除已有索引: {INDEX_NAME}")
        es.indices.delete(index=INDEX_NAME)

    es.indices.create(index=INDEX_NAME, settings=ES_SETTINGS, mappings=ES_MAPPINGS)
    print(f"[ES] 索引创建成功: {INDEX_NAME}")

    info = es.indices.get(index=INDEX_NAME)
    props = list(info[INDEX_NAME]["mappings"]["properties"].keys())
    print(f"[ES] 字段数: {len(props)}")
    print(f"[ES] 字段列表: {props}")


if __name__ == "__main__":
    main()
