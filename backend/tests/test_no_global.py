"""T-1.12 — 静态检查：app/ 无模块级可变全局客户端单例、无 os.getenv 重复解析。"""
from __future__ import annotations

import re
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
    """扫描应用包（app/ 与 cli/）—— `src/` 已并入 app/。"""
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


# ── 分层方向守卫（T-1.13）──────────────────────────────────────


def _layer_files(layer: str) -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "app" / layer
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_reverse_layer_imports():
    """`application` / `infrastructure` 不得 import `interface`。

    回归：`AppContainer` 单例曾定义在 `app/interface/deps.py`，导致 application 与
    infrastructure 为了取容器反向 import interface（19 + 20 处），只能靠函数内 import
    规避循环——分层名存实亡。单例下沉到 `infrastructure/container.py` 后本守卫才成立。

    例外：`infrastructure/ws_manager.py` 的注释里提到过这个历史，不算 import。
    """
    pattern = re.compile(r"^\s*(from|import)\s+app\.interface\b")
    hits = []
    for layer in ("application", "infrastructure"):
        for path in _layer_files(layer):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(line):
                    hits.append(f"{path.name}:{n}: {line.strip()}")
    assert not hits, "跨层反向依赖（application/infrastructure → interface）:\n" + "\n".join(hits)


def test_domain_does_not_import_other_layers():
    """domain 不得 import application / infrastructure / interface。"""
    pattern = re.compile(r"^\s*(from|import)\s+app\.(application|infrastructure|interface)\b")
    hits = []
    for path in _layer_files("domain"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.match(line):
                hits.append(f"{path.name}:{n}: {line.strip()}")
    assert not hits, "domain 越层依赖:\n" + "\n".join(hits)


def test_container_singleton_lives_in_infrastructure():
    """容器单例的真源必须在 infrastructure 层（interface/deps 只做 re-export）。"""
    from app.infrastructure import container as infra_container

    assert hasattr(infra_container, "get_container")
    assert hasattr(infra_container, "set_container")

    # re-export 后是同一个函数对象，保证 set_container 对两条导入路径都生效
    from app.interface.deps import get_container as via_deps

    assert via_deps is infra_container.get_container, (
        "interface/deps 的 get_container 必须是 infrastructure 的同一对象；"
        "若是各自定义的包装，两个单例会分裂"
    )
