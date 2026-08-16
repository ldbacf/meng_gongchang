"""T-3.9 — 双 worker 并发：batch 锁 + XAUTOCLAIM 前置查锁。"""
from __future__ import annotations

import pytest

from app.infrastructure.redis.queue_adapter import QueueAdapter


@pytest.mark.asyncio
async def test_batch_lock_exclusive(fake_redis):
    """同一批仅一个消费者能认领锁。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq")
    assert await q.acquire_lock("b1") is True
    assert await q.acquire_lock("b1") is False  # 第二个拿不到
    await q.release_lock("b1")
    assert await q.acquire_lock("b1") is True  # 释放后可再拿


@pytest.mark.asyncio
async def test_claim_skips_locked_pending(fake_redis):
    """XAUTOCLAIM 前置查锁：锁未释放的孤儿 pending 不回收（防同批双跑）。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=0.01, max_delivery=3)
    await q.enqueue("b2", ["m1"], "tk_1")
    job = await q.claim(timeout=0)
    assert job is not None
    # 不 ack，模拟长处理；worker 持有批锁
    await q.acquire_lock("b2")
    # 可见性超时后另一个 worker claim：XAUTOCLAIM 应跳过（锁住），不回收
    assert await q.claim(timeout=0) is None
    # 释放锁后可回收（等可见性超时）
    await q.release_lock("b2")
    import asyncio

    await asyncio.sleep(0.05)
    recovered = await q.claim(timeout=0)
    assert recovered is not None
    assert recovered.message.batch_id == "b2"
    await q.ack(recovered.entry_id)


@pytest.mark.asyncio
async def test_superseded_skipped(fake_redis):
    """superseded 标记：旧批消息回收后短路（不重投、不 DLQ）。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=0.01, max_delivery=3)
    await q.enqueue("b3", ["m1"], "tk_1")
    job = await q.claim(timeout=0)
    assert job is not None
    await q.mark_superseded("b3")
    # 不 ack；可见性超时后回收应跳过（superseded）
    assert await q.claim(timeout=0) is None
    await q.release_lock("b3")
    assert await fake_redis.xlen("dlq") == 0  # 未进 DLQ
