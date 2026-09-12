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


def test_llm_module_removed():
    """src/llm.py 整模块已删除（get_chat_model 转发壳一并移除；调用方直连 container.get_llm()）。"""
    assert not (_ROOT / "src/llm.py").exists()
    # 调用方经容器取模型
    text = _read("src/llm_answer.py")
    assert "get_container().get_llm().get_chat_model(" in text


def test_fetch_l0_meta_uses_kb_es_index():
    """fetch_l0_meta 不再硬编码 index='chunks'，改由调用方线程 es_index（QaState.kb.es_index）。"""
    text = _read("app/application/graphs/rag/nodes/_common.py")
    assert 'es_index or "chunks"' in text
    assert 'index="chunks"' not in text
    cite_text = _read("app/application/graphs/rag/nodes/cite.py")
    assert "fetch_l0_meta(reranked, es_index=kb.get(\"es_index\"))" in cite_text


def test_legacy_src_shims_removed():
    """重构遗留的零引用转发 shim 已删除（阶段 5 收尾）。

    - src/reranker.py / src/worker.py / src/mineru_client.py：纯转发、零引用。
    - src/chunker.py：仅测试引用，测试已改为直接 import domain 入口。
    """
    for gone in ("src/reranker.py", "src/worker.py", "src/mineru_client.py", "src/chunker.py"):
        assert not (_ROOT / gone).exists(), f"遗留 shim 未删除: {gone}"


def test_main_has_no_dead_imports():
    """src/main.py 不再 import 已无引用的符号（阶段 5 收尾发现的死 import）。"""
    text = _read("src/main.py")
    for sym in ("from src.mineru_client import", "TokenExhausted",
                "init_buckets,", "MINERU_BATCH_SIZE",
                "from src.db import async_session, engine",
                "from collections import defaultdict"):
        assert sym not in text, f"src/main.py 仍有死 import: {sym}"


def test_scripts_dir_gone():
    """scripts/ 目录已退役（内容全部迁入 cli/）；手动脚本在 manual/（非 tests/）。"""
    scripts = _ROOT / "scripts"
    leftover = [p.name for p in scripts.rglob("*")] if scripts.exists() else []
    assert leftover == [], f"scripts/ 仍有残留: {leftover}"
    assert (_ROOT / "manual").is_dir(), "手动脚本目录 manual/ 不存在"
    assert not (_ROOT / "test").exists(), "旧 test/ 目录仍在（应已改名为 manual/）"


def test_forwarding_shims_removed():
    """阶段 5 收尾：4 个纯转发壳已删除（调用方直连 settings / container）。"""
    for gone in ("src/config.py", "src/redis_client.py", "src/minio_client.py", "src/llm.py"):
        assert not (_ROOT / gone).exists(), f"转发壳未删除: {gone}"


def test_no_imports_from_removed_shims():
    """全仓库不再 import 已删的转发壳（防止回退）。"""
    banned = ("from src.config", "from src.redis_client", "from src.minio_client",
              "from src.llm import", "import src.config", "import src.minio_client",
              "import src.redis_client")
    self_path = Path(__file__).resolve()
    offenders = []
    for root in ("app", "src", "cli", "tests", "manual"):
        for path in (_ROOT / root).rglob("*.py"):
            if "__pycache__" in str(path) or path.resolve() == self_path:
                continue  # 跳过本文件（下面的 banned 字面量就是它自己）
            text = path.read_text(encoding="utf-8")
            for b in banned:
                if b in text:
                    offenders.append(f"{path.relative_to(_ROOT)}: {b}")
    assert offenders == [], f"仍引用已删转发壳: {offenders}"
