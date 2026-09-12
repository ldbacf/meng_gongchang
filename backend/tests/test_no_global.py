"""T-1.12 — 静态检查：app/ 无模块级可变全局客户端单例、无 os.getenv 重复解析。"""
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
    """扫描应用包（app/ 与 cli/）—— `src/` 已于阶段 5 目录整理并入 app/。"""
    root = Path(__file__).resolve().parent.parent
    files = sorted((root / "app").rglob("*.py")) + sorted((root / "cli").rglob("*.py"))
    return [p for p in files if "__pycache__" not in p.parts]


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
    """架构红线：禁止跨模块 import 私有名（search._get_es / _connect_milvus / key_manager._tokens）。

    注：只禁**跨模块**访问（如 `key_manager._tokens`）；模块内部 `self._tokens` 属正常封装。
    """
    forbidden_imports = [
        "from app.infrastructure.search import _get_es",
        "from app.infrastructure.search import _connect_milvus",
        "import _get_es",
        "key_manager._tokens",
    ]
    hits = []
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        for pat in forbidden_imports:
            if pat in text:
                hits.append(f"{path}: {pat}")
    assert not hits, "\n".join(hits)
