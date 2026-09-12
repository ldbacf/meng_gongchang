"""T-2.7 — chunk_document golden 回归（重构前冻结基线，搬家式重构后不得回归）。

- golden 基线路径：`tests/golden/sample_chunks.json`（重构**前**跑 sample fixtures 冻结）。
- 覆盖：完整 L0（标题/摘要/关键词）、L1 分段（按标题边界）、L2 表格（v2 表注回填、
  表引用段落）、doc_id=article_id 口径。
- 直接 import domain 唯一入口（`src.chunker` 转发层已随阶段 5 清理移除）。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.domain.chunking.chunk_document import chunk_document

_FIXTURES = Path(__file__).parent / "fixtures"
_GOLDEN = Path(__file__).parent / "golden"
_MD5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _sample_inputs():
    full_md = (_FIXTURES / "sample_full.md").read_text(encoding="utf-8")
    meta = json.loads((_FIXTURES / "sample_meta.json").read_text(encoding="utf-8"))
    cl_v2 = json.loads(
        (_FIXTURES / "sample_content_list_v2.json").read_text(encoding="utf-8")
    )
    return full_md, cl_v2, meta


def test_chunk_document_golden():
    result = chunk_document(_MD5, *_sample_inputs())
    golden = json.loads((_GOLDEN / "sample_chunks.json").read_text(encoding="utf-8"))
    assert result == golden


def test_chunk_golden_v2_footnote_filled():
    """v2 表注回填：L2 表格 content 含『表注』。"""
    result = chunk_document(_MD5, *_sample_inputs())
    l2 = [c for c in result["chunks"] if c["level"] == "L2"]
    assert l2, "应至少有一个 L2 表格 chunk"
    assert "表注" in l2[0]["content"]


def test_chunk_golden_table_reference():
    """表引用段落进入 L2 的 referring 池。"""
    result = chunk_document(_MD5, *_sample_inputs())
    l2 = next(c for c in result["chunks"] if c["level"] == "L2")
    assert "作者结论" in l2["content"]
    assert "高血压是最常见的慢性病之一" in l2["content"]
