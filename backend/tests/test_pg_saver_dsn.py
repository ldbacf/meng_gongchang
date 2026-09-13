"""T-5.14 — checkpointer DSN 归一。

两点：① SQLAlchemy asyncpg 前缀 → psycopg 可用格式；
② `localhost` → `127.0.0.1`（本机 Windows 上 psycopg async 连 localhost 会静默卡死，
   排查记录见 docs/error_ok/启动端口问题记录.md 问题 4）。
"""
from __future__ import annotations

from app.infrastructure.checkpoint.pg_saver import normalize_dsn


def test_asyncpg_prefix_stripped():
    assert (
        normalize_dsn("postgresql+asyncpg://u:p@db:5432/x")
        == "postgresql://u:p@db:5432/x"
    )


def test_localhost_rewritten_to_ipv4_with_port():
    assert (
        normalize_dsn("postgresql+asyncpg://u:p@localhost:5432/mineru_pipeline")
        == "postgresql://u:p@127.0.0.1:5432/mineru_pipeline"
    )


def test_localhost_rewritten_to_ipv4_without_port():
    assert (
        normalize_dsn("postgresql://u:p@localhost/mineru_pipeline")
        == "postgresql://u:p@127.0.0.1/mineru_pipeline"
    )


def test_other_hosts_untouched():
    # compose 服务名 / 显式 IPv4 都不动
    assert normalize_dsn("postgresql://u:p@postgres:5432/x") == "postgresql://u:p@postgres:5432/x"
    assert normalize_dsn("postgresql://u:p@127.0.0.1:5432/x") == "postgresql://u:p@127.0.0.1:5432/x"
    # 主机名里含 "localhost" 但不以它结尾的，不误伤（无 @localhost 段）
    assert normalize_dsn("postgresql://u:p@notlocalhost:5432/x") == "postgresql://u:p@notlocalhost:5432/x"
