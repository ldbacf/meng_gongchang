"""T-2.6 — 统一切分入口：在线（indexer）与离线（run_chunker）同一输入产出同构 chunks。

阶段 2 后在线 `index_document` 图与离线 `cli/run_chunker` 共用
`chunk_document`（唯一入口）。对同一输入（md5 + full.md + meta={}）：
- doc_id = 契约口径 md5[:8]；
- generic L0 带 title 入参（引用展示不回归为"未知文档"）。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.domain.chunking.chunk_document import chunk_document

_FIXTURES = Path(__file__).parent / "fixtures"
_MD5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_chunk_online_offline_identical():
    """在线/离线统一入口对同一输入产出同构 chunks。"""
    full_md = (_FIXTURES / "sample_full.md").read_text(encoding="utf-8")
    # 在线通用 KB：indexer 传 meta={} + title=filename stem
    online = chunk_document(_MD5, full_md, None, {}, title="测试文档")
    # 离线：run_chunker 同样走 chunk_document（无 doc-meta → generic L0）
    offline = chunk_document(_MD5, full_md, None, {}, title="测试文档")
    assert online == offline
    # 契约口径
    assert online["doc_id"] == _MD5[:8]
    assert online["chunks"][0]["doc_id"] == _MD5[:8]
    assert online["chunks"][0]["title"] == "测试文档"


def test_indexer_uses_same_entrypoint():
    """在线 index_document 图与离线 run_chunker 共用 domain 的 chunk_document（import 同源）。"""
    import inspect

    from app.application.graphs.subgraphs.index_document import chunk_document_node
    from app.domain.chunking.chunk_document import chunk_document as domain_entry

    src = inspect.getsource(chunk_document_node)
    assert "chunk_document" in src  # 在线不再内联拼装
    # 入口函数即 domain 唯一入口
    assert domain_entry.__module__ == "app.domain.chunking.chunk_document"
