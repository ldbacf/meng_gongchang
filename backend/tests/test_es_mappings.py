"""T-1.3 — ES mapping 单一真相源：规范脚本与在线自动建共用同一常量。"""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.es.es_mappings import (
    ES_MAPPINGS,
    ES_SETTINGS,
    GENERIC_KB_EXTRA_MAPPING,
    build_generic_kb_mapping,
)


def test_es_mapping_single_source_with_init_es():
    """cli.init_es 与在线自动建共用同一 ES_MAPPINGS/ES_SETTINGS 常量（同一对象）。"""
    from cli import init_es as mod

    assert mod.ES_MAPPINGS is ES_MAPPINGS
    assert mod.ES_SETTINGS is ES_SETTINGS


def test_online_mapping_is_superset_of_canonical():
    """在线自动建（indexer）的 mapping 是规范 mapping 的超集，含通用补充字段。"""
    merged = build_generic_kb_mapping()

    assert merged["dynamic"] == "strict"
    # 完整 26 字段都在（超集）
    for field in ES_MAPPINGS["properties"]:
        assert field in merged["properties"], f"缺少字段 {field}"
    # 通用 KB 特有字段已补充
    for field in GENERIC_KB_EXTRA_MAPPING:
        assert field in merged["properties"], f"缺少通用字段 {field}"


def test_metadata_must_be_text_for_match():
    """search.py 对 metadata.title_cn/keywords_cn 做 match（文本语义），必须 text+ik_smart。"""
    merged = build_generic_kb_mapping()
    md = merged["properties"]["metadata"]
    assert md["type"] == "object"
    assert md["properties"]["title_cn"]["type"] == "text"
    assert md["properties"]["title_cn"]["analyzer"] == "ik_smart"
    assert md["properties"]["keywords_cn"]["type"] == "text"


def test_heading_depth_type_short():
    """合并后 heading_depth 保持 short（与规范 mapping 一致）。"""
    merged = build_generic_kb_mapping()
    assert merged["properties"]["heading_depth"]["type"] == "short"


def test_es_settings_ik_smart():
    """ES_SETTINGS 带 ik_smart 自定义分词器。"""
    assert ES_SETTINGS["analysis"]["analyzer"]["ik_analyzer"]["tokenizer"] == "ik_smart"
