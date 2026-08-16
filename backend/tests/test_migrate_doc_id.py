"""T-3.12 — doc_id 存量迁移：口径统一 + chunk_id 重算。"""
from __future__ import annotations

from scripts.migrate_doc_id import _new_chunk_id, normalize_doc_id


def test_normalize_doc_id():
    # 32 位 hex（在线旧口径 md5）→ md5[:8]
    assert normalize_doc_id("0123456789abcdef0123456789abcdef") == "01234567"
    # article_id 形态不变
    assert normalize_doc_id("A-2024-001") == "A-2024-001"
    # 短 id / 非 hex 不变
    assert normalize_doc_id("abc") == "abc"


def test_new_chunk_id_prefix_replace():
    old_doc = "0123456789abcdef0123456789abcdef"
    new_doc = "01234567"
    assert _new_chunk_id(f"{old_doc}__L0", old_doc, new_doc) == f"{new_doc}__L0"
    assert _new_chunk_id(f"{old_doc}__L1__1_p1", old_doc, new_doc) == f"{new_doc}__L1__1_p1"
    assert _new_chunk_id(f"{old_doc}__L2__table_3", old_doc, new_doc) == f"{new_doc}__L2__table_3"
    # 前缀不匹配 → 原样
    assert _new_chunk_id("other__L0", old_doc, new_doc) == "other__L0"
