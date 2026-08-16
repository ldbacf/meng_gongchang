"""T-1.4 — Milvus schema 单一真相源：规范脚本与在线自动建共用同一 schema；dim/nlist 读 Settings。"""
from __future__ import annotations

from app.infrastructure.milvus import schema as mv_schema
from app.infrastructure.settings import get_settings


def test_milvus_field_list_matches_contract():
    fields = mv_schema.build_milvus_fields(dim=1024)
    names = [f.name for f in fields]
    assert names == [
        "chunk_id", "doc_id", "doi", "level", "chunk_type",
        "journal", "section", "article_type", "title_cn", "embedding",
    ]
    assert fields[0].is_primary
    assert fields[0].dtype.name == "VARCHAR"
    assert fields[-1].params["dim"] == 1024


def test_milvus_schema_single_source_with_init_script():
    """init_milvus 脚本与在线自动建共用 build_milvus_schema/build_milvus_index_params。"""
    from pathlib import Path

    import importlib.util

    backend = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "init_milvus_check", backend / "scripts" / "init_milvus.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # noqa: 仅读取导入，不执行 main
    assert mod.build_milvus_schema is mv_schema.build_milvus_schema
    assert mod.build_milvus_index_params is mv_schema.build_milvus_index_params


def test_milvus_dim_nlist_from_settings():
    """dim/nlist 读 Settings（默认 1024 / 128），脚本与在线建不硬编码。"""
    s = get_settings()
    assert s.embedding_dim == 1024
    assert s.milvus_nlist == 128
    # build_milvus_schema 默认 dim 来自 Settings
    schema = mv_schema.build_milvus_schema()
    emb = next(f for f in schema.fields if f.name == "embedding")
    assert emb.params["dim"] == s.embedding_dim
    params = mv_schema.build_milvus_index_params()
    assert params["metric_type"] == "COSINE"
    assert params["params"]["nlist"] == s.milvus_nlist


def test_milvus_truncate_field():
    assert mv_schema.truncate_field("x" * 100, "doc_id") == "x" * 32
    assert mv_schema.truncate_field("ok", "doc_id") == "ok"
