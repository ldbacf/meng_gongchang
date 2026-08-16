"""T-1.5 / T-1.6 — Redis Streams 队列 at-least-once + payload 无明文 token。"""
from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.redis.queue_adapter import BatchMessage, QueueAdapter


def test_batch_message_no_plaintext_token():
    """T-1.6: BatchMessage 序列化只含 token_id，无明文 token 字段。"""
    msg = BatchMessage(batch_id="b1", md5_list=["m1"], token_id="tk_1")
    payload = msg.to_json()
    assert "tk_1" in payload
    assert "token_id" in payload
    # 不存在独立的 "token" 字段（排除 token_id 本身）
    assert '"token"' not in payload
    parsed = BatchMessage.from_json(payload)
    assert parsed.token_id == "tk_1"
    assert parsed.attempts == 0


@pytest.mark.asyncio
async def test_queue_roundtrip_and_ack(fake_redis):
    """enqueue → claim → ack；ack 后不再重投。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq")
    await q.enqueue("b1", ["m1", "m2"], "tk_1")

    job = await q.claim(timeout=0)
    assert job is not None
    assert job.message.batch_id == "b1"
    assert job.message.md5_list == ["m1", "m2"]
    assert job.message.token_id == "tk_1"

    await q.ack(job.entry_id)
    assert await q.claim(timeout=0) is None


@pytest.mark.asyncio
async def test_queue_visibility_timeout_recover(fake_redis):
    """T-1.5: claim 后未 ack，可见性超时后回到可 claim（崩溃恢复，A-1.3）。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=0.01, max_delivery=3)
    await q.enqueue("b1", ["m1"], "tk_1")

    job = await q.claim(timeout=0)
    assert job is not None
    # 不 ack —— 模拟 worker 崩溃
    await asyncio.sleep(0.05)  # 超过可见性超时
    recovered = await q.claim(timeout=0)
    assert recovered is not None
    assert recovered.message.batch_id == "b1"


@pytest.mark.asyncio
async def test_queue_dlq_after_max_delivery(fake_redis):
    """T-1.5: 连续失败（claim→nack）超过 max_delivery → 进 DLQ。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=0.01, max_delivery=3)
    await q.enqueue("b1", ["m1"], "tk_1")

    for _ in range(5):
        job = await q.claim(timeout=0)
        if job is None:
            break
        await q.nack(job.entry_id)
    assert await fake_redis.xlen("dlq") >= 1


@pytest.mark.asyncio
async def test_queue_claim_resolves_token_via_vault(fake_redis):
    """消息里的 token_id 可经 TokenVault 解析回明文（Redis 全程无明文）。"""
    from app.infrastructure.vault import TokenVault

    vault = TokenVault(["tok_a", "tok_b"])
    q = QueueAdapter(fake_redis, "s", "g", "dlq")
    await q.enqueue("b1", ["m1"], "tk_2")
    job = await q.claim(timeout=0)
    assert vault.resolve(job.message.token_id) == "tok_b"
    await q.ack(job.entry_id)
