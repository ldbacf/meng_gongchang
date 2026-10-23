"""T-1.7 / T-1.8 — 额度 Redis 记账：reserve/commit/refund + 跨日期重置。

Lua 原子脚本需真实 Redis（fakeredis 2.37 不支持 eval），故用 testcontainers Redis。
无 Docker 环境自动 skip。
"""
from __future__ import annotations

import pytest

from app.infrastructure.redis.quota_store_redis import QuotaStoreRedis


@pytest.fixture
def redis_url():
    """真实 Redis（Lua 原子脚本需真实实例）。

    连本机 Redis（docker compose 8 服务），用 db=15 隔离 + 每个测试前 flushdb；
    无可用 Redis 时 skip。用 127.0.0.1 而非 localhost：Windows 下 localhost
    可能解析为 ::1（IPv6）而 Redis 绑在 IPv4。
    """
    import asyncio

    import redis.asyncio as aioredis

    url = "redis://127.0.0.1:6379/15"
    try:
        async def _flush():
            r = aioredis.from_url(
                url, decode_responses=True,
                socket_connect_timeout=3, socket_timeout=3,
            )
            await r.ping()
            await r.flushdb()  # 隔离：清空测试库，避免测试间残留
            await r.aclose()

        asyncio.run(_flush())
        return url
    except Exception as e:
        pytest.skip(f"无可用 Redis，跳过额度集成测试: {e}")
        return


def _async_redis(url: str):
    import redis.asyncio as aioredis

    return aioredis.from_url(url, decode_responses=True)


@pytest.mark.asyncio
async def test_quota_reserve_commit_refund(redis_url):
    """T-1.7: reserve 预占 → commit 扣额；reserve → refund 退回。"""
    r = _async_redis(redis_url)
    store = QuotaStoreRedis(r)
    await store.reserve("tk_1", 10, "res-1")
    assert await store.balance("tk_1") == 10

    await store.commit("res-1")
    assert await store.balance("tk_1") == 10  # commit 只确认，不再重复扣

    await store.reserve("tk_1", 5, "res-2")
    assert await store.balance("tk_1") == 15

    await store.refund("tk_1", 5, "res-2")
    assert await store.balance("tk_1") == 10

    # 已 committed 的 reservation 不能再 refund
    assert await store.refund("tk_1", 10, "res-1") is False
    assert await store.balance("tk_1") == 10
    await r.aclose()


@pytest.mark.asyncio
async def test_quota_cross_client_consistent(redis_url):
    """T-1.7: 两个 Redis 客户端（模拟跨进程）额度一致、无互相覆盖。"""
    r1 = _async_redis(redis_url)
    r2 = _async_redis(redis_url)
    store1, store2 = QuotaStoreRedis(r1), QuotaStoreRedis(r2)

    await store1.reserve("tk_1", 7, "res-a")
    await store2.reserve("tk_1", 5, "res-b")
    assert await store1.balance("tk_1") == 12
    assert await store2.balance("tk_1") == 12

    await store2.refund("tk_1", 5, "res-b")
    assert await store1.balance("tk_1") == 7
    await r1.aclose()
    await r2.aclose()


@pytest.mark.asyncio
async def test_quota_daily_reset(redis_url):
    """T-1.8: 跨日期自动重置（注入 ClockPort）。"""
    r = _async_redis(redis_url)
    current = {"d": "2026-08-16"}  # 可变日期，reserve 与 balance 读同一日期
    store = QuotaStoreRedis(r, clock=lambda: current["d"])

    await store.reserve("tk_1", 10, "res-day1")
    assert await store.balance("tk_1") == 10  # 8-16

    current["d"] = "2026-08-17"
    await store.reserve("tk_1", 7, "res-day2")
    assert await store.balance("tk_1") == 7  # 8-17 自动重置
    await r.aclose()


@pytest.mark.asyncio
async def test_quota_is_exhausted(redis_url):
    """is_exhausted 的三个分支。

    回归：曾写成 `all((await self.balance(kid)) >= max_pages for kid in key_ids)`——
    `await` 在生成器表达式内会让整个表达式变成 async_generator，`all()` 收到它直接
    `TypeError: 'async_generator' object is not iterable`。该 bug 让
    `/api/v1/tokens/usage` 稳定 500，而此前的额度用例没覆盖这个方法。
    """
    r = _async_redis(redis_url)
    store = QuotaStoreRedis(r)

    # 空列表：没有 key 不算「全部用尽」
    assert await store.is_exhausted([], 10) is False

    # 部分用尽：只要还有一个 key 有余量就不算用尽
    await store.reserve("tk_1", 10, "res-x1")
    await store.reserve("tk_2", 3, "res-x2")
    assert await store.is_exhausted(["tk_1", "tk_2"], 10) is False

    # 全部用尽
    await store.reserve("tk_2", 7, "res-x3")
    assert await store.is_exhausted(["tk_1", "tk_2"], 10) is True

    await r.aclose()
