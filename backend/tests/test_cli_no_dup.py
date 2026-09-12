"""T-5.1 — cli 收敛守卫：无 `sys.path.insert` 直 import；管线逻辑复用 service/图。

用 AST 检查**实际代码**（不受 docstring/注释里提到这些名字的干扰）。
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CLI = _ROOT / "cli"


def _tree(name: str) -> ast.Module:
    return ast.parse((_CLI / name).read_text(encoding="utf-8"))


def _imported_names(name: str) -> set[str]:
    """模块内所有 import 的符号（from X import a,b → {a,b}；import a.b → {a.b}）。"""
    out: set[str] = set()
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                out.add(a.name)
                out.add(f"{node.module}.{a.name}" if node.module else a.name)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def _calls_sys_path_insert(name: str) -> bool:
    for node in ast.walk(_tree(name)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "insert"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "sys"
        ):
            return True
    return False


def test_cli_has_no_sys_path_insert():
    offenders = [p.name for p in _CLI.glob("*.py") if _calls_sys_path_insert(p.name)]
    assert offenders == [], f"cli/ 仍调用 sys.path.insert: {offenders}"


def test_cli_modules_exist():
    expected = {
        "init_es.py", "init_milvus.py", "import_es.py", "import_milvus.py",
        "run_chunker.py", "scan_submit.py", "check_status.py", "list_bucket.py",
        "backfill_document_tasks.py", "migrate_doc_id.py", "download_model.py",
    }
    assert expected <= {p.name for p in _CLI.glob("*.py")}


def test_cli_reuses_pipeline_seams():
    # import_milvus：复用 src.indexer.milvus_insert（不内联模型编码）
    assert "milvus_insert" in _imported_names("import_milvus.py")
    # import_es：复用 src.indexer.es_bulk_write（不内联 helpers.bulk）
    assert "es_bulk_write" in _imported_names("import_es.py")
    # run_chunker：复用 domain 唯一切分入口
    assert "chunk_document" in _imported_names("run_chunker.py")


def test_scripts_dir_retired():
    scripts = _ROOT / "scripts"
    leftover = [p.name for p in scripts.glob("*.py")] if scripts.exists() else []
    assert leftover == [], f"scripts/ 未退役: {leftover}"
