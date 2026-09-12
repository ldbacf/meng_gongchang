"""T-5.9 — 死代码清理静态守卫：删除清单内的符号/端点不复存在。

（静态源码检查，不跑外部服务。）
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _assert_absent(rel: str, names: list[str]):
    text = _read(rel)
    for n in names:
        assert n not in text, f"{rel} 仍含已删除符号: {n}"


def test_pre_signed_pdf_endpoint_removed():
    """预签名 PDF 端点 + 三套回退 helper 已删除（仅保留 /pdf/stream 代理流单路径）。"""
    _assert_absent("src/main.py", ["get_document_pdf", "_try_document_task_pdf", "_try_minio_direct", "_build_pdf_response"])
    assert "/documents/{doc_id}/pdf/stream" in _read("src/main.py")
    assert '"/documents/{doc_id}/pdf"' not in _read("src/main.py").replace('pdf/stream', '')


def test_process_document_removed():
    """src/indexer.process_document（内联 embed 循环死代码）已删除；es_bulk_write/milvus_insert 保留。"""
    text = _read("src/indexer.py")
    assert "def process_document" not in text
    assert "es_bulk_write" in text and "milvus_insert" in text
    # 在线索引路径经 index_document 图（chunk_document_node），非 indexer 内联
    assert "chunk_document" in _read("app/application/graphs/subgraphs/index_document.py")


def test_llm_wrappers_removed():
    """src/llm 的重复 embedding wrapper（get_embedding_model/get_sentence_transformer）已删除；get_chat_model 保留。"""
    text = _read("src/llm.py")
    assert "get_embedding_model" not in text
    assert "def get_sentence_transformer" not in text
    assert "def get_chat_model" in text


def test_fetch_l0_meta_uses_kb_es_index():
    """fetch_l0_meta 不再硬编码 index='chunks'，改由调用方线程 es_index（QaState.kb.es_index）。"""
    text = _read("app/application/graphs/rag/nodes/_common.py")
    assert 'es_index or "chunks"' in text
    assert 'index="chunks"' not in text
    cite_text = _read("app/application/graphs/rag/nodes/cite.py")
    assert "fetch_l0_meta(reranked, es_index=kb.get(\"es_index\"))" in cite_text
