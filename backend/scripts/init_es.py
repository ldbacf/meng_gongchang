"""
Elasticsearch 索引初始化 — 一键创建 chunks 索引（IK 分词器 + 完整 mapping）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elasticsearch import Elasticsearch

from src.config import ES_HOST, ES_PORT, ES_USER, ES_PASSWORD, ES_INDEX

INDEX_NAME = ES_INDEX

SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "analyzer": {
            "ik_analyzer": {
                "type": "custom",
                "tokenizer": "ik_smart",
            }
        }
    },
}

MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "chunk_id":        {"type": "keyword"},
        "doc_id":          {"type": "keyword"},
        "level":           {"type": "keyword"},
        "chunk_type":      {"type": "keyword"},
        "doi":             {"type": "keyword"},

        "journal":         {"type": "keyword"},
        "source":          {"type": "keyword"},
        "section":         {"type": "keyword"},
        "article_type":    {"type": "keyword"},
        "title_cn":        {"type": "text", "analyzer": "ik_smart"},
        "title_en":        {"type": "text", "analyzer": "standard"},
        "authors_cn":      {"type": "keyword"},
        "keywords_cn":     {"type": "keyword"},
        "keywords_en":     {"type": "keyword"},
        "md5":             {"type": "keyword"},
        "uuid":            {"type": "keyword"},

        "heading_stack":   {"type": "keyword"},
        "heading_depth":   {"type": "short"},
        "table_number":    {"type": "short"},
        "table_caption":   {"type": "text", "analyzer": "ik_smart"},
        "table_caption_en": {"type": "text", "analyzer": "standard"},
        "html_size":       {"type": "integer"},
        "refers_to_tables": {"type": "keyword"},

        "content":         {"type": "text", "analyzer": "ik_smart"},
        "html_body":       {"type": "text", "index": False},
    },
}


def _get_es_client() -> Elasticsearch:
    kwargs = {"request_timeout": 30}
    if ES_USER and ES_PASSWORD:
        return Elasticsearch(
            f"http://{ES_USER}:{ES_PASSWORD}@{ES_HOST}:{ES_PORT}",
            **kwargs,
        )
    return Elasticsearch(f"http://{ES_HOST}:{ES_PORT}", **kwargs)


def main():
    es = _get_es_client()

    if es.indices.exists(index=INDEX_NAME):
        print(f"[ES] 删除已有索引: {INDEX_NAME}")
        es.indices.delete(index=INDEX_NAME)

    es.indices.create(index=INDEX_NAME, settings=SETTINGS, mappings=MAPPINGS)
    print(f"[ES] 索引创建成功: {INDEX_NAME}")

    info = es.indices.get(index=INDEX_NAME)
    props = list(info[INDEX_NAME]["mappings"]["properties"].keys())
    print(f"[ES] 字段数: {len(props)}")
    print(f"[ES] 字段列表: {props}")


if __name__ == "__main__":
    main()
