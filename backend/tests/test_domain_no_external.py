"""T-2.8 — 静态检查：domain/ 零外部依赖（仅 stdlib import）。"""
from __future__ import annotations

from pathlib import Path

_FORBIDDEN_LIBS = ("sqlalchemy", "httpx", "redis", "pymilvus", "elasticsearch", "langchain")


def test_domain_no_external_imports():
    root = Path(__file__).resolve().parent.parent / "app" / "domain"
    hits = []
    for path in sorted(root.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for lib in _FORBIDDEN_LIBS:
                if lib in stripped:
                    hits.append(f"{path}: {stripped}")
    assert not hits, "\n".join(hits)


def test_domain_pure_stdlib_modules():
    """domain 关键模块只 import stdlib（白名单式验证）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app" / "domain"
    # 抽查纯函数资产模块
    for rel in (
        "chunking/parser.py",
        "chunking/chunk_document.py",
        "retrieval/rrf.py",
        "retrieval/citation.py",
        "rag/intent.py",
        "knowledge_base.py",
        "document/task_status.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("from app.") or stripped.startswith("import app."):
                continue  # domain 内部跨包引用允许
            if stripped.startswith(("import ", "from ")):
                for lib in _FORBIDDEN_LIBS:
                    assert lib not in stripped, f"{rel}: {stripped}"
