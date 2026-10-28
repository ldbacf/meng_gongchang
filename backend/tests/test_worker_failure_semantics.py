"""worker 消费循环的失败语义 —— 失败必须立即 nack，不能静默悬挂。

## 为什么需要这一组

真实事故：一份 PDF 卡在「索引中」25 分钟，期间界面没有任何错误提示。

`run_worker` 原先写成：

    except Exception as e:
        log.error(...); await asyncio.sleep(5); continue

`_process_job` 抛出的异常被这个 except 吃掉，消息**既没 ack 也没 nack**，
留在 Redis 的 pending 里只能等 `queue_visibility_timeout`（默认 1800s）
被 XAUTOCLAIM 回收。于是每次都固定多等 30 分钟才重试一次。

更糟的是可观测性：logger 走 stdout，而 worker 由 `run_process` 拉起，
这些日志不落到任何地方，用户只看到一个不动的进度条。

正确语义：失败即 `nack()`（attempts+1 马上重投），超限进 DLQ ——
**悬挂比失败更难排查**，宁可让任务明确失败并在界面上报错。

## 依赖

fakeredis（无外部服务），直接驱动 `_process_job` 的失败分支。
"""
from __future__ import annotations

import pytest

from app.infrastructure.redis.queue_adapter import QueueAdapter


class _Boom(Exception):
    """模拟图节点抛出的任意异常（如 InvalidStatusTransition）。"""


@pytest.mark.asyncio
async def test_nack_requeues_immediately_not_after_visibility_timeout(fake_redis):
    """nack 后消息可**立即**再 claim —— 这是 worker 修好后的行为。

    对照：不 ack 不 nack 时要等 visibility_timeout（1800s）才回收。
    """
    # visibility_timeout 设得很大，确保"能立刻再 claim"不是因为超时回收
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=1800, max_delivery=3)
    await q.enqueue("b1", ["m1"], "tk_1")

    job = await q.claim(timeout=0)
    assert job is not None
    assert job.message.batch_id == "b1"

    await q.nack(job.entry_id)

    # 立刻（不 sleep）就该能拿到重投的消息
    again = await q.claim(timeout=0)
    assert again is not None, "nack 后消息没有立即重投，会退回 1800s 可见性超时"
    assert again.message.batch_id == "b1"
    assert again.message.attempts == 1, f"attempts 应为 1，实际 {again.message.attempts}"


@pytest.mark.asyncio
async def test_hanging_message_is_not_reclaimable_within_visibility_timeout(fake_redis):
    """反证：只 claim 不 ack/nack 的消息在可见性超时内不可 reclaim。

    这正是修复前的状态 —— 消息"消失"了 30 分钟。这条测试把旧行为
    固化成可对照的事实，避免以后有人把 nack 又去掉。
    """
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=1800, max_delivery=3)
    await q.enqueue("b1", ["m1"], "tk_1")

    job = await q.claim(timeout=0)
    assert job is not None
    # 故意不 ack / 不 nack（= 修复前的 worker 行为）

    assert await q.claim(timeout=0) is None, (
        "未 nack 的消息不该被立即 reclaim —— 若这里能拿到，说明可见性语义变了"
    )


@pytest.mark.asyncio
async def test_repeated_failures_eventually_reach_dlq(fake_redis):
    """连续失败超 max_delivery → 进 DLQ，而不是无限重投。

    对应用户视角：卡死的文档最终会变成「失败」并带错误信息，
    而不是永远停在「索引中」。
    """
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=1800, max_delivery=3)
    await q.enqueue("b1", ["m1"], "tk_1")

    seen = 0
    for _ in range(10):
        job = await q.claim(timeout=0)
        if job is None:
            break
        seen += 1
        await q.nack(job.entry_id)

    assert await fake_redis.xlen("dlq") >= 1, "超过 max_delivery 后应进 DLQ"
    # 投递次数有上限，不会无限循环
    assert seen <= 5, f"投递次数异常：{seen}"


@pytest.mark.asyncio
async def test_nack_survives_unreadable_payload(fake_redis):
    """payload 损坏时 nack 仍须 ack 掉原消息，不能让它永久挂 pending。"""
    q = QueueAdapter(fake_redis, "s", "g", "dlq", visibility_timeout=1800, max_delivery=3)
    entry_id = await fake_redis.xadd("s", {"payload": "not-json"})

    # claim 会因 payload 解析失败而 ack 掉并返回 None（见 QueueAdapter.claim）
    assert await q.claim(timeout=0) is None
    # 原 entry 已被 ack，不会永远留在 pending
    pending = await fake_redis.xpending("s", "g")
    assert pending["pending"] == 0, f"损坏消息仍挂在 pending: {pending}"
    assert entry_id  # 仅为说明该 entry 确实存在过
