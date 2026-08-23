"""T-2.3 — status DB CHECK：插入非法 status 被 DB 拒绝（集成，需真实 Postgres）。

领域层非法迁移已由 `test_task_status_machine.py` 覆盖；DB 层 CHECK 需真实 PG。
优先连本机 PG（docker compose 8 服务），用独立临时库跑 alembic 0003 + 非法插入；
无 PG 时 skip。CI 无 PG 则跳过（集成测试）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


_TMP_DB = "_phase2_status_check"


@pytest.fixture(scope="module")
def pg_dsn():
    """连本机 PG（docker 8 服务），动态建临时库验证 CHECK。"""
    import asyncpg

    admin_dsn = "postgresql://mineru:mineru123@127.0.0.1:5432/postgres"
    dsn = f"postgresql://mineru:mineru123@127.0.0.1:5432/{_TMP_DB}"
    try:
        async def _create():
            conn = await asyncpg.connect(admin_dsn, timeout=3)
            await conn.execute(f"DROP DATABASE IF EXISTS {_TMP_DB}")
            await conn.execute(f"CREATE DATABASE {_TMP_DB}")
            await conn.close()

        asyncio.run(_create())
        yield dsn
        # teardown：清理临时库
        async def _drop():
            conn = await asyncpg.connect(admin_dsn, timeout=3)
            await conn.execute(f"DROP DATABASE IF EXISTS {_TMP_DB}")
            await conn.close()

        asyncio.run(_drop())
    except Exception as e:
        pytest.skip(f"无可用 Postgres，跳过 DB CHECK 集成测试: {e}")
        return


@pytest.fixture(scope="module")
def migrated(pg_dsn):
    """在临时库上跑 alembic upgrade head（0001→0003）。

    alembic env 经 Settings 读 `DATABASE_URL`，需 asyncpg driver 前缀。
    """
    import os
    import subprocess

    async_db_url = pg_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    env = dict(os.environ, DATABASE_URL=async_db_url)
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, f"alembic 迁移失败: {r.stderr}"
    return True


@pytest.mark.asyncio
async def test_status_db_check_rejects_invalid(migrated, pg_dsn):
    """DB CHECK：status 非法值（如 'cancelled'）插入被拒。"""
    import asyncpg

    conn = await asyncpg.connect(pg_dsn, timeout=3)
    try:
        # 合法值可插入
        row = await conn.fetchrow(
            "INSERT INTO document_tasks (id, md5, original_name, raw_minio_path, status) "
            "VALUES (gen_random_uuid(), 'aaaa', 't', 'p', 'pending') RETURNING status"
        )
        assert row["status"] == "pending"
        # 非法值被 CHECK 拒绝
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                "INSERT INTO document_tasks (id, md5, original_name, raw_minio_path, status) "
                "VALUES (gen_random_uuid(), 'bbbb', 't', 'p', 'cancelled')"
            )
        # 清理
        await conn.execute("DELETE FROM document_tasks")
    finally:
        await conn.close()


def test_status_db_enum_sql_offline():
    """0003 迁移离线 SQL 含 status CHECK（无需 DB）。"""
    import subprocess

    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, r.stderr
    assert "ck_document_tasks_status" in r.stdout
    assert "ck_knowledge_bases_kb_kind" in r.stdout
