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
    """创建 AsyncPostgresSaver（返回后由调用方负责 close 连接）。"""
    import psycopg

    conn = await psycopg.AsyncConnection.connect(normalize_dsn(dsn))
    saver = AsyncPostgresSaver(conn)
    await saver.setup()  # 幂等校验（表已由 Alembic 0002 建好）
    return saver


async def close_pg_saver(saver: AsyncPostgresSaver) -> None:
    """关闭 saver 持有的连接。"""
    try:
        await saver.close()
    except Exception:
        pass
