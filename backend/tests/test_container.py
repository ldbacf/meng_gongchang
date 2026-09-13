"""T-1.1 / T-1.2 — AppContainer 生命周期与可注入性。"""
from __future__ import annotations

import pytest

from app.infrastructure.container import AppContainer
from app.infrastructure.settings import Settings


def _settings(embedding_mode: str = "local") -> Settings:
    """显式 Settings（不读 .env）——测试不应随开发者本地配置（EMBEDDING_MODE 等）变化。"""
    return Settings(_env_file=None, jwt_secret_key="pytest-test-secret", embedding_mode=embedding_mode)


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
    """两种 embedding 模式的 fake：local 用 get_hf_embeddings，remote 用 check_health。

    remote 分支由 `EMBEDDING_MODE` 决定（读 .env），两种方法都实现才能两种模式下都跑通。
    """

    def __init__(self):
        self.released = False
        self.hf_calls = 0
        self.health_calls = 0

    def get_hf_embeddings(self):
        self.hf_calls += 1
        return object()

    def check_health(self) -> bool:
        self.health_calls += 1
        return True

    def release(self):
        self.released = True


@pytest.mark.asyncio
async def test_container_lifecycle_idempotent():
    """T-1.1: start/close 幂等；close 后连接释放回调被调用（local 模式预热模型）。"""
    engine, minio, emb = FakeEngine(), FakeMinio(), FakeEmbedder()
    c = AppContainer(
        settings=_settings("local"),
        fakes={"engine": engine, "minio": minio, "embedder": emb},
    )

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
async def test_container_start_remote_probes_health():
    """T-1.1b: remote 模式走 /health 探针，不加载本地模型。"""
    engine, minio, emb = FakeEngine(), FakeMinio(), FakeEmbedder()
    c = AppContainer(
        settings=_settings("remote"),
        fakes={"engine": engine, "minio": minio, "embedder": emb},
    )

    await c.start()
    assert emb.health_calls == 1
    assert emb.hf_calls == 0  # remote 不预热本地模型
    await c.close()


@pytest.mark.asyncio
async def test_container_start_tolerates_partial_fake_embedder():
    """T-1.1c: fake embedder 只实现部分方法时 start() 不崩（两分支都用 getattr 容错）。"""
    class _Bare:
        def release(self):
            pass

    engine, minio = FakeEngine(), FakeMinio()
    for mode in ("local", "remote"):
        c = AppContainer(
            settings=_settings(mode),
            fakes={"engine": engine, "minio": minio, "embedder": _Bare()},
        )
        await c.start()  # 不应抛 AttributeError
        await c.close()


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
