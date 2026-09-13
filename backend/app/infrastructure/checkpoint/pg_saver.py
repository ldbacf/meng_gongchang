"""AsyncPostgresSaver 工厂（langgraph-checkpoint-postgres 3.1.2）。

- **导入路径**：`langgraph.checkpoint.postgres.aio`（3.1.2 的 async saver 在 aio 子模块，
  `postgres` 顶层只有 BasePostgresSaver）。
- DDL 已由 Alembic 0002 版本化迁移建好（checkpoints/checkpoint_blobs/...），
  `setup()` 仅幂等校验（红线 C2，不依赖 `.setup()` 建表）。
- Windows 下 psycopg async 需 SelectorEventLoop（ProactorEventLoop 不支持）——
  worker 进程入口负责设置事件循环策略。
"""
from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def normalize_dsn(dsn: str) -> str:
    """SQLAlchemy asyncpg URL → psycopg 可用的 postgresql:// 格式。

    顺带把 host 的 `localhost` 归一成 `127.0.0.1`：本机 Windows 上 **psycopg async 连
    `localhost` 会静默卡死**（不报错、不超时，服务停在启动中途），而 asyncpg 容忍——
    所以只有 checkpointer 这一步中招，极难排查。语义上 localhost ≡ 127.0.0.1，归一安全。
    （排查记录：`docs/error_ok/启动端口问题记录.md` 问题 4）
    """
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return (
        dsn.replace("@localhost:", "@127.0.0.1:")
           .replace("@localhost/", "@127.0.0.1/")
           .replace("@localhost?", "@127.0.0.1?")
    )


async def create_pg_saver(dsn: str) -> AsyncPostgresSaver:
    """创建 AsyncPostgresSaver（返回后由调用方负责 close 连接）。

    **连接参数必须与库自身的 `AsyncPostgresSaver.from_conn_string` 一致**
    （`autocommit=True, prepare_threshold=0, row_factory=dict_row`）。曾因只写
    `psycopg.AsyncConnection.connect(dsn)` 踩坑：saver 内部
    `get_connection()` 对裸连接只 yield、**不 commit**，于是每次 `aput` 的写入都
    留在未提交事务里，连接一关即回滚——**checkpoint 一行都不落库**，且全程不报错
    （图照常跑完、`setup()` 也"成功"），静默失效。后果是 C6 每-superstep checkpoint、
    崩溃续跑、retry 全都形同虚设。

    - `autocommit=True`：决定性（否则写入永不提交）。
    - `row_factory=dict_row`：库内部按 `row["v"]` 取值，元组行会 TypeError。
    - `prepare_threshold=0`：与库一致，避免连接池外的 prepared statement 缓存问题。
    """
    import psycopg
    from psycopg.rows import dict_row

    conn = await psycopg.AsyncConnection.connect(
        normalize_dsn(dsn),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        saver = AsyncPostgresSaver(conn)
        await saver.setup()  # 幂等校验（表已由 Alembic 0002 建好）
    except Exception:
        await _aclose_quiet(conn)  # 建 saver / setup 失败不留半开连接
        raise
    return saver


async def _aclose_quiet(conn) -> None:
    try:
        await conn.close()
    except Exception:
        pass


async def close_pg_saver(saver: AsyncPostgresSaver) -> None:
    """关闭 saver 持有的连接。

    注意：`AsyncPostgresSaver` **没有** `close()`（3.1.2），占用的是 `saver.conn`；
    以前调 `saver.close()` 被 except 吞掉 → 连接永不释放。这里改为关连接本身。
    """
    conn = getattr(saver, "conn", None)
    if conn is not None:
        await _aclose_quiet(conn)
