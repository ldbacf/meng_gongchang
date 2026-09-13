"""pytest 共享 fixture。

以契约/纯函数单测为主（不依赖真实外部服务）；
集成类测试在此扩展 fakeredis / testcontainers fixture（ES/Milvus/Redis/PG）。
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

TEST_JWT_SECRET = "pytest-test-secret"


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
