"""pytest 共享 fixture。

以契约/纯函数单测为主（不依赖真实外部服务）；
集成类测试在此扩展 fakeredis / testcontainers fixture（ES/Milvus/Redis/PG）。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

TEST_JWT_SECRET = "pytest-test-secret"

# ── 测试库隔离 ──────────────────────────────────────────────────────────────
# 真实事故：`test_rag_graph` 的 fixture 用 `AppContainer()`（读 .env → mineru_pipeline）
# 插了 `qt_xxxx` 用户和「测试会话」，teardown 的 delete 没 commit，事务关闭即回滚，
# 于是每跑一次 pytest 就往开发库留一批垃圾（实测累积 214 个账号 / 214 个会话）。
#
# 现在：`POSTGRES_DB` 在**导入期**就改指向独立临时库（环境变量优先于 .env，
# 且早于任何 `get_settings()` 调用 —— 它是 lru_cache，晚设就固化不进去了）。
# 建库与 `alembic upgrade head` 由 `isolated_db` fixture 负责，用完 DROP。
#
# 为什么不改 `DATABASE_URL`：`test_settings.py::test_env_override` 依赖
# `POSTGRES_HOST/PORT` 真被使用；改 db 名不影响那条断言。
TEST_DB = "_pytest_isolated"
os.environ["POSTGRES_DB"] = TEST_DB

#: 与 alembic.ini / docker compose 一致的超级用户，用于建库/删库。
_ADMIN_DSN = "postgresql://mineru:mineru123@127.0.0.1:5432/postgres"


def _pg_reachable() -> bool:
    """本机 PG 端口是否可达；不可达时依赖 DB 的测试 skip（CI 无 PG 仍可通过）。"""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def isolated_db() -> Iterator[str]:
    """建独立测试库 + alembic 建表；结束后 DROP。

    需要真实 PG 的测试模块请声明 `pytestmark = pytest.mark.usefixtures("isolated_db")`。
    无 PG 时该 fixture 直接 skip，不会误连开发库。
    """
    import asyncpg

    if not _pg_reachable():
        pytest.skip("本机无 Postgres，跳过需要真实数据库的集成测试")

    async def _admin(sql: str) -> None:
        conn = await asyncpg.connect(_ADMIN_DSN, timeout=5)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    # FORCE：容器连接池可能还开着旧连接，PG13+ 支持强制断开
    asyncio.run(_admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    asyncio.run(_admin(f"CREATE DATABASE {TEST_DB}"))

    backend_root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=dict(os.environ),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, f"测试库 alembic 迁移失败: {r.stderr}"

    dsn = f"postgresql+asyncpg://mineru:mineru123@127.0.0.1:5432/{TEST_DB}"
    yield dsn

    asyncio.run(_admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))


# ── 事件循环：Windows 下统一 SelectorEventLoop ──────────────────────────────
# 直接设 policy（而非覆盖 `event_loop_policy` fixture —— 那在 pytest-asyncio 1.4 已弃用，
# 且新钩子 `pytest_asyncio_loop_factories` 一旦注册就必须对所有平台返回映射）。
# 插件在未显式指定 loop factory 时，正是回落到"当前 policy"来造循环，故此处设置即生效。
#
# 两点理由：
# 1. **与生产一致** —— `medrag-api`（app/run_api.py）就设 SelectorEventLoopPolicy；
#    测试跑同一条循环，才能在这里暴露 psycopg/事件循环类问题（如 checkpointer 静默失效）。
# 2. **psycopg async 在 ProactorEventLoop 上直接不可用**（InterfaceError），不设则任何走
#    checkpointer 的测试必然失败，而生产是好的 —— 假阴性。
# asyncpg（SQLAlchemy engine）两种循环都兼容；全仓无 `asyncio.subprocess` 用法，
# 而 Proactor 的唯一刚需正是子进程 —— 该刚需不存在，故可安全全局切换。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@contextmanager
def env(**kwargs: str | None) -> Iterator[None]:
    """临时设置环境变量（None 表示删除）。"""
    saved = {}
    try:
        for k, v in kwargs.items():
            saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def env_ctx() -> Any:
    return env


@pytest.fixture
def fake_redis_server():
    """fakeredis 共享 server（可派生多个客户端模拟跨进程）。"""
    import fakeredis

    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis(fake_redis_server):
    """fakeredis 客户端（模拟 Redis；Streams 支持，PubSub 在 2.37 不支持）。"""
    import fakeredis

    r = fakeredis.aioredis.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield r
