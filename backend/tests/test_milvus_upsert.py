"""T-1.10 — Milvus 幂等写入：按 chunk_id 先删后插，二次 upsert 不撞主键。"""
from __future__ import annotations

from app.infrastructure.adapters.milvus import MilvusAdapter


class _FakeCollection:
    """mock pymilvus Collection：记录调用顺序。"""

    def __init__(self):
        self.calls: list[tuple] = []

    def delete(self, expr: str):
        self.calls.append(("delete", expr))

    def insert(self, cols):
        self.calls.append(("insert", cols))
        return object()

    def flush(self):
        self.calls.append(("flush",))


class _FakeMilvus(MilvusAdapter):
    """跳过真实连接（仅测 upsert_batch 逻辑）。"""

    def __init__(self):
        pass

    def connect(self):
        pass


def test_milvus_upsert_delete_before_insert():
    mv = _FakeMilvus()
    col = _FakeCollection()
    chunks = [
        {
            "chunk_id": "d__L0", "doc_id": "d", "doi": "", "level": "L0",
            "chunk_type": "paper", "journal": "", "section": "",
            "article_type": "", "title_cn": "", "vector": [0.1] * 1024,
        },
        {
            "chunk_id": "d__L1__1", "doc_id": "d", "doi": "", "level": "L1",
            "chunk_type": "paragraph", "journal": "", "section": "",
            "article_type": "", "title_cn": "", "vector": [0.2] * 1024,
        },
    ]

    n = mv.upsert_batch(col, chunks)

    assert n == 2
    kinds = [c[0] for c in col.calls]
    assert kinds[0] == "delete"
    assert kinds[1] == "insert"
    assert kinds[-1] == "flush"
    # 删除按 chunk_id 批量（幂等：二次写入不撞主键）
    assert 'chunk_id in ["d__L0", "d__L1__1"]' in col.calls[0][1]
    # 插入按共享 10 字段 schema 传列
    assert len(col.calls[1][1]) == 10


def test_milvus_upsert_skips_no_vector():
    mv = _FakeMilvus()
    col = _FakeCollection()
    chunks = [{"chunk_id": "x__L0", "doc_id": "x"}]  # 无 vector

    assert mv.upsert_batch(col, chunks) == 0
    assert col.calls == []


def test_milvus_upsert_truncates_doc_id():
    mv = _FakeMilvus()
    col = _FakeCollection()
    long_doc = "a" * 64
    chunks = [{"chunk_id": "x__L0", "doc_id": long_doc, "vector": [0.1]}]

    mv.upsert_batch(col, chunks)
    insert_cols = col.calls[1][1]
    # 第 2 列是 doc_id，截断到 32
    assert all(len(v) <= 32 for v in insert_cols[1])
