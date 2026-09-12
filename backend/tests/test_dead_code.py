"""T-5.9 — 死代码 / 目录归位静态守卫。

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


# ── 死代码清理 ─────────────────────────────────────────────


def test_pre_signed_pdf_endpoint_removed():
    """预签名 PDF 端点 + 三套回退 helper 已删除（仅保留 /pdf/stream 代理流单路径）。"""
    _assert_absent(
        "app/main.py",
        ["get_document_pdf", "_try_document_task_pdf", "_try_minio_direct", "_build_pdf_response"],
    )
    assert "/documents/{doc_id}/pdf/stream" in _read("app/main.py")
    assert '"/documents/{doc_id}/pdf"' not in _read("app/main.py").replace("pdf/stream", "")


def test_process_document_removed():
    """process_document（内联 embed 循环死代码）已删除；es_bulk_write/milvus_insert 保留。"""
    text = _read("app/infrastructure/indexer.py")
    assert "def process_document" not in text
    assert "es_bulk_write" in text and "milvus_insert" in text
    # 在线索引路径经 index_document 图（chunk_document_node），非 indexer 内联
    assert "chunk_document" in _read("app/application/graphs/subgraphs/index_document.py")


def test_llm_answer_uses_container():
    """回答模型经容器取（无 src/llm 转发壳）。"""
    text = _read("app/infrastructure/adapters/llm_answer.py")
    assert "get_container().get_llm().get_chat_model(" in text


def test_fetch_l0_meta_uses_kb_es_index():
    """fetch_l0_meta 不再硬编码 index='chunks'，改由调用方线程 es_index（QaState.kb.es_index）。"""
    text = _read("app/application/graphs/rag/nodes/_common.py")
    assert 'es_index or "chunks"' in text
    assert 'index="chunks"' not in text
    cite_text = _read("app/application/graphs/rag/nodes/cite.py")
    assert "fetch_l0_meta(reranked, es_index=kb.get(\"es_index\"))" in cite_text


def test_main_has_no_dead_imports():
    """app/main.py 不再 import 已无引用的符号。"""
    text = _read("app/main.py")
    for sym in ("TokenExhausted", "init_buckets,", "MINERU_BATCH_SIZE",
                "from app.infrastructure.db.session import async_session, engine",
                "from collections import defaultdict"):
        assert sym not in text, f"app/main.py 仍有死 import: {sym}"


# ── 目录归位（src/ 并入 app/）──────────────────


def test_src_dir_fully_removed():
    """src/ 目录已整体并入 app/（S1~S4 目录整理完成）。"""
    assert not (_ROOT / "src").exists(), "src/ 目录仍存在"
    assert not (_ROOT / "scripts").exists(), "scripts/ 目录仍存在"


def test_manual_dir_not_test_dir():
    """手动脚本在 manual/（非 tests/，避免 pytest 误收集）。"""
    assert (_ROOT / "manual").is_dir(), "手动脚本目录 manual/ 不存在"
    assert not (_ROOT / "test").exists(), "旧 test/ 目录仍在（应已改名为 manual/）"


def test_new_module_layout_exists():
    """归位后的关键模块就位。"""
    for rel in (
        "app/main.py",
        "app/run_api.py",
        "app/interface/routers/chat.py",
        "app/interface/schemas.py",
        "app/interface/security.py",
        "app/infrastructure/db/models.py",
        "app/infrastructure/db/session.py",
        "app/infrastructure/search.py",
        "app/infrastructure/indexer.py",
        "app/infrastructure/adapters/llm_answer.py",
        "app/infrastructure/ws_manager.py",
        "app/infrastructure/key_manager.py",
    ):
        assert (_ROOT / rel).is_file(), f"归位后缺失: {rel}"
    # 空壳目录 app/interface/api/ 已删
    assert not (_ROOT / "app/interface/api").exists(), "空壳 app/interface/api/ 仍在"


def test_no_residual_imports_from_src():
    """全仓库（应用包/CLI/测试/手动脚本）不再 import 旧 src.* 命名空间。"""
    banned = (
        "from src.", "import src.",
        "from src/", "src.main:app",
    )
    self_path = Path(__file__).resolve()
    offenders = []
    for root in ("app", "cli", "tests", "manual", "alembic"):
        base = _ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in str(path) or path.resolve() == self_path:
                continue
            text = path.read_text(encoding="utf-8")
            for b in banned:
                if b in text:
                    offenders.append(f"{path.relative_to(_ROOT)}: {b}")
    assert offenders == [], f"仍引用旧 src.* 命名空间: {offenders}"
