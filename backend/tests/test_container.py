"""T-1.1 / T-1.2 — AppContainer 生命周期与可注入性。"""
from __future__ import annotations

import pytest

from app.infrastructure.container import AppContainer


class FakeEngine:
    """模拟 AsyncEngine（SQLAlchemy）：begin 直接返回自身当 connection。"""

    def __init__(self):
        self.disposed = False

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return None

    async def dispose(self):
        self.disposed = True


class FakeMinio:
    def __init__(self):
        self.init_calls = 0

    async def init_buckets(self):
        self.init_calls += 1


class FakeEmbedder:
    def __init__(self):
        self.released = False
        self.hf_calls = 0

    def get_hf_embeddings(self):
        self.hf_calls += 1
        return object()

    def release(self):
        self.released = True


@pytest.mark.asyncio
async def test_container_lifecycle_idempotent():
    """T-1.1: start/close 幂等；close 后连接释放回调被调用。"""
    engine, minio, emb = FakeEngine(), FakeMinio(), FakeEmbedder()
    c = AppContainer(fakes={"engine": engine, "minio": minio, "embedder": emb})

    await c.start()
    await c.start()  # 幂等：不重复预热
    assert minio.init_calls == 1
    assert emb.hf_calls == 1

    await c.close()
    await c.close()  # 幂等：dispose 只跑一次
    assert engine.disposed
    assert emb.released

    # close 后可重建（start→close→start 可用）
    await c.start()
    assert minio.init_calls == 2


@pytest.mark.asyncio
async def test_container_injectable_fakes():
    """T-1.2: 容器可注入 fake ES/Milvus/Redis，getter 返回 fake。"""
    fake_es, fake_mv, fake_redis = object(), object(), object()
    c = AppContainer(fakes={"es": fake_es, "milvus": fake_mv, "redis": fake_redis})

    assert c.get_es() is fake_es
    assert c.get_milvus() is fake_mv
    assert c.get_redis() is fake_redis


def test_container_not_started_lazy_no_clients():
    """未 start 的容器不创建任何客户端（lazy）。"""
    c = AppContainer(fakes={"engine": FakeEngine()})
    assert c._es is None
    assert c._redis is None
    assert c._milvus is None
