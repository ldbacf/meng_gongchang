"""Elasticsearch 索引初始化 — 创建 chunks 索引（IK 分词 + 完整 mapping）。

⚠️ 红线：本命令会 **DROP 并重建** `chunks` 索引，清空已入库数据！
只允许在全新环境（无任何数据）使用。判断方法：先查
`curl localhost:9200/chunks/_count`，非 0 就绝不能运行。

用法: python -m cli.init_es
"""
from __future__ import annotations

from elasticsearch import Elasticsearch

from app.infrastructure.es.es_mappings import ES_MAPPINGS, ES_SETTINGS
from app.infrastructure.settings import get_settings


def _get_es_client() -> Elasticsearch:
    s = get_settings()
    kwargs = {"request_timeout": 30}
    if s.es_user and s.es_password:
        return Elasticsearch(f"http://{s.es_user}:{s.es_password}@{s.es_host}:{s.es_port}", **kwargs)
    return Elasticsearch(f"http://{s.es_host}:{s.es_port}", **kwargs)


def main() -> None:
    index_name = get_settings().es_index
    es = _get_es_client()
    if es.indices.exists(index=index_name):
        print(f"[ES] 删除已有索引: {index_name}")
        es.indices.delete(index=index_name)

    es.indices.create(index=index_name, settings=ES_SETTINGS, mappings=ES_MAPPINGS)
    print(f"[ES] 索引创建成功: {index_name}")

    info = es.indices.get(index=index_name)
    props = list(info[INDEX_NAME]["mappings"]["properties"].keys())
    print(f"[ES] 字段数: {len(props)}")
    print(f"[ES] 字段列表: {props}")


if __name__ == "__main__":
    main()
