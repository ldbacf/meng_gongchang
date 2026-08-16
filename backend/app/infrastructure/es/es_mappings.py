"""Elasticsearch 索引 schema 唯一真相源 — 规范脚本与在线自动建共用。

- `ES_SETTINGS` / `ES_MAPPINGS`：与 `scripts/init_es.py` 原定义逐字一致
  （ik_smart 分词、`dynamic: strict`、26 字段），规范脚本行为零变化。
- `GENERIC_KB_EXTRA_MAPPING`：通用知识库 chunk 特有字段（`title` / `metadata`）。
  strict 模式下缺字段会被拒绝，在线自动建必须合并；`metadata.title_cn/keywords_cn`
  声明为 text+ik_smart —— `search.py` 对 `metadata.title_cn/keywords_cn` 做 match 语义加分。
- 存量已创建的通用 KB 索引停在旧宽松 mapping（字段类型不可变更），
  "双轨合一"仅对新建索引成立，存量待阶段 3 统一重建。
"""
from __future__ import annotations

ES_SETTINGS = {
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

ES_MAPPINGS = {
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

# 通用知识库 chunk（chunker.py 通用路径）特有、而完整 mapping 没有的字段
GENERIC_KB_EXTRA_MAPPING = {
    "title": {"type": "text", "analyzer": "ik_smart"},
    "metadata": {
        "type": "object",
        "properties": {
            "title_cn": {"type": "text", "analyzer": "ik_smart"},
            "keywords_cn": {"type": "text", "analyzer": "ik_smart"},
        },
    },
}


def build_generic_kb_mapping() -> dict:
    """在线自动建通用 KB 索引用的 mapping：完整 26 字段 + 通用补充。"""
    return {
        "dynamic": "strict",
        "properties": {**ES_MAPPINGS["properties"], **GENERIC_KB_EXTRA_MAPPING},
    }
