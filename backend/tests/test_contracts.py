"""chunk 契约与 SearchHit 契约测试。"""
from __future__ import annotations

from app.domain.chunking.chunk_contract import (
    Chunk,
    ChunkLevel,
    ChunkType,
    chunk_id_for_l0,
    chunk_id_for_l1,
    chunk_id_for_l2_table,
    doc_id_from,
)
from app.domain.retrieval.search_hit import RANK_SENTINEL, SearchHit


def test_doc_id_prefers_article_id():
    assert doc_id_from("A-2024-001", "0123456789abcdef") == "A-2024-001"


def test_doc_id_fallback_md5_prefix():
    assert doc_id_from("", "0123456789abcdef") == "01234567"


def test_chunk_id_patterns():
    doc = "A-1"
    assert chunk_id_for_l0(doc) == "A-1__L0"
    assert chunk_id_for_l1(doc, "1") == "A-1__L1__1"
    assert chunk_id_for_l1(doc, "1", idx=1) == "A-1__L1__1_p1"
    assert chunk_id_for_l1(doc, "") == "A-1__L1__body"
    assert chunk_id_for_l2_table(doc, 3) == "A-1__L2__table_3"


def test_chunk_to_index_dict_fields():
    c = Chunk(
        chunk_id="d__L1__1",
        doc_id="d",
        level=ChunkLevel.L1,
        chunk_type=ChunkType.PARAGRAPH,
        content="正文",
        heading_stack=["引言"],
        refers_to_tables=[2],
        vector=[0.1, 0.2],
    )
    d = c.to_index_dict()
    assert d["chunk_id"] == "d__L1__1"
    assert d["heading_stack"] == ["引言"]
    assert d["refers_to_tables"] == [2]
    assert "vector" not in d  # 向量不落 ES _source


def test_search_hit_sentinels():
    h = SearchHit(doc_id="d")
    assert h.rank_milvus == RANK_SENTINEL
    assert h.rank_es == RANK_SENTINEL
    assert not h.from_milvus and not h.from_es
    h.rank_milvus = 1
    assert h.from_milvus
