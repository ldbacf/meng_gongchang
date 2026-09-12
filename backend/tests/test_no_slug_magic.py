"""T-2.9 — 静态检查：slug 魔法串仅存在于 seed（main.py）+ 迁移基线 + KB 常量。

仓库无 seeder.py，默认库 seed 在 `src/main.py`（lifespan 创建）。
业务分支（worker/admin/chat/backfill）一律用 kb_kind，禁止 slug 判断。
"""
from __future__ import annotations

from pathlib import Path

_SEED_FILES = {"main.py"}  # src/ 下允许出现 slug 的 seed 文件
_DOMAIN_ALLOWED = {"knowledge_base.py"}  # domain 只允许 KB 常量定义处


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_no_slug_magic_in_src():
    src_root = _project_root() / "src"
    for path in sorted(src_root.rglob("*.py")):
        if path.name in _SEED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        assert "zhong_guo_quan_ke" not in text, f"{path}"


def test_no_slug_magic_in_domain():
    domain_root = _project_root() / "app" / "domain"
    for path in sorted(domain_root.rglob("*.py")):
        if path.name in _DOMAIN_ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        assert "zhong_guo_quan_ke" not in text, f"{path}"


def test_no_slug_magic_in_cli():
    cli_root = _project_root() / "cli"
    for path in sorted(cli_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "zhong_guo_quan_ke" not in text, f"{path}"
