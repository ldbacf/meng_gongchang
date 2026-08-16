"""T-1.12 — 静态检查：src/ 无模块级可变全局客户端单例、无 os.getenv 重复解析。"""
from __future__ import annotations

from pathlib import Path

_FORBIDDEN = [
    "global _ES_CLIENT",
    "global _MILVUS_CONNECTED",
    "global _EMBED_MODEL",
    "global _manager",
    "global _pool",
    "global _client",
    "global _CHAT_MODEL",
    "global _RAW_ST_MODEL",
]


def _src_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "src"
    return sorted(root.rglob("*.py"))


def test_no_module_global_client_singletons():
    hits = []
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        for pat in _FORBIDDEN:
            if pat in text:
                hits.append(f"{path}: {pat}")
    assert not hits, "\n".join(hits)


def test_no_os_getenv_in_src():
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        # 匹配函数调用（docstring 提及 "os.getenv" 不算）
        assert "os.getenv(" not in text, f"{path}"


def test_no_private_cross_imports():
    """架构红线：禁止 import src.search._get_es / _connect_milvus / key_manager._tokens。"""
    forbidden_imports = [
        "from src.search import _get_es",
        "from src.search import _connect_milvus",
        "import _get_es",
        "._tokens",
    ]
    hits = []
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        for pat in forbidden_imports:
            if pat in text:
                hits.append(f"{path}: {pat}")
    assert not hits, "\n".join(hits)
