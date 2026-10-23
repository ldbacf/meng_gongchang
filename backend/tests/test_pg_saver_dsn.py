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


def test_create_pg_saver_has_connect_timeout():
    """连接参数必须带 connect_timeout（回归：缺它时 PG 不可达会永久挂住）。

    psycopg 默认不是快速失败：PG 端口不通时 `AsyncConnection.connect()` 会无限等待，
    表现为 `container.start()` 永久挂住——进程活着、端口不通、健康检查探不到、
    编排也不会重启，比直接崩溃难排查得多。
    """
    import inspect

    from app.infrastructure.checkpoint.pg_saver import create_pg_saver

    sig = inspect.signature(create_pg_saver)
    assert "connect_timeout" in sig.parameters
    assert sig.parameters["connect_timeout"].default == 5

    src = inspect.getsource(create_pg_saver)
    assert "connect_timeout=connect_timeout" in src, "connect_timeout 未传给 psycopg"

    # 容器启动侧还要有 asyncio.wait_for 兜住 setup() 等后续步骤
    from app.infrastructure.container import AppContainer

    start_src = inspect.getsource(AppContainer.start)
    assert "wait_for" in start_src, "container.start 缺少 wait_for 超时保护"
