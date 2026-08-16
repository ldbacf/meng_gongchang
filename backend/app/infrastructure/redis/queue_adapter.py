"""可靠队列适配器 — Redis Streams + 消费者组（at-least-once）。

语义：
- `enqueue`：XADD 到 stream（自动建 group）。
- `claim`：**每轮先 XAUTOCLAIM 回收 idle 超可见性超时的孤儿 pending**（kill-worker 恢复，
  见 A-1.3），再 XREADGROUP BLOCK 读新消息。回收时 attempts+1，超 `max_delivery` 进 DLQ。
- `ack`：处理完成确认（XACK）。
- `nack`：处理失败 → XACK + 重新 XADD（attempts+1），超限进 DLQ。
- `dead_letter`：直接进 DLQ stream。

消息格式（contract 4.2.1）：`{batch_id, md5_list, token_id, submit_ts, attempts}`，
**不含明文 MinerU token**（token_id ↔ 明文仅在容器 TokenVault 内解析）。

注意：worker 处理完一批才 ack；单批最坏时长（MAX_POLL_TIME 1200s + 索引）必须小于
`visibility_timeout`（默认 1800s），否则另一 worker 会误回收仍在正常处理的批。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from redis.exceptions import ResponseError


@dataclass
class BatchMessage:
    batch_id: str
    md5_list: list[str]
    token_id: str
    submit_ts: float = 0.0
    attempts: int = 0
    mode: str = "submit"  # "submit" 新批 | "resume" checkpoint 续跑（retry 用）

    def to_json(self) -> str:
        return json.dumps(
            {
                "batch_id": self.batch_id,
                "md5_list": self.md5_list,
                "token_id": self.token_id,
                "submit_ts": self.submit_ts,
                "attempts": self.attempts,
                "mode": self.mode,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "BatchMessage":
        data = json.loads(raw)
        return cls(
            batch_id=data["batch_id"],
            md5_list=data.get("md5_list", []),
            token_id=data.get("token_id", ""),
            submit_ts=data.get("submit_ts", 0.0),
            attempts=data.get("attempts", 0),
            mode=data.get("mode", "submit"),
        )


@dataclass
class QueuedJob:
    entry_id: str
    message: BatchMessage


# 消费者名：固定名，重启后能 XAUTOCLAIM 回收自己 kill 前留下的 pending
_CONSUMER = "worker"


class QueueAdapter:
    def __init__(
        self,
        redis,
        stream: str,
        group: str,
        dlq: str,
        visibility_timeout: int = 1800,
        max_delivery: int = 3,
    ):
        self._redis = redis
        self._stream = stream
        self._group = group
        self._dlq = dlq
        self._visibility_timeout = visibility_timeout
        self._max_delivery = max_delivery

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    # ── 写 ────────────────────────────────────────────────────

    async def enqueue(
        self, batch_id: str, md5_list: list[str], token_id: str, mode: str = "submit"
    ) -> str:
        """XADD 一条批消息（自动建 group）。返回 entry id。

        mode: "submit" 新批 / "resume" checkpoint 续跑（retry 用，batch_id 是原批=thread 键）。
        """
        await self._ensure_group()
        msg = BatchMessage(
            batch_id=batch_id,
            md5_list=md5_list,
            token_id=token_id,
            submit_ts=time.time(),
            attempts=0,
            mode=mode,
        )
        return await self._redis.xadd(self._stream, {"payload": msg.to_json()})

    async def _xadd_dlq(self, msg: BatchMessage) -> str:
        return await self._redis.xadd(
            self._dlq, {"payload": msg.to_json(), "reason": "max_delivery"}
        )

    # ── 读 / ack ──────────────────────────────────────────────

    async def claim(self, timeout: float = 5.0) -> QueuedJob | None:
        """取一条待处理批。

        先回收孤儿 pending（idle 超 `visibility_timeout`），再 XREADGROUP BLOCK 读新消息。
        """
        await self._ensure_group()

        # 1) 回收孤儿 pending（kill-worker / 崩溃恢复）
        while True:
            try:
                _next, entries, _deleted = await self._redis.xautoclaim(
                    self._stream, self._group, _CONSUMER,
                    int(self._visibility_timeout * 1000), "0", count=1,
                )
            except ResponseError:
                break  # stream 尚无 pending / 命令不支持
            if not entries:
                break
            entry_id, fields = entries[0]
            try:
                msg = BatchMessage.from_json(fields["payload"])
            except (KeyError, json.JSONDecodeError):
                await self._redis.xack(self._stream, self._group, entry_id)
                continue
            # 前置检查：batch 锁未释放（有 worker 在途）或已 superseded（MinerU 重提交）
            # → 不回收，留 pending（锁持有者释放后 / 下次 claim 再试），防同批双跑
            if await self._redis.exists(f"batch:{msg.batch_id}:lock") or \
                    await self._redis.exists(f"batch:{msg.batch_id}:superseded"):
                break
            # attempts+1，超限进 DLQ，否则重投（新 entry 经 '>' 重新读取）
            msg.attempts += 1
            await self._redis.xack(self._stream, self._group, entry_id)
            if msg.attempts > self._max_delivery:
                await self._xadd_dlq(msg)
                continue
            await self._redis.xadd(self._stream, {"payload": msg.to_json()})
            # 重投的 entry 会在下面的 XREADGROUP 里作为新消息读到

        # 2) 阻塞读新消息
        try:
            result = await self._redis.xreadgroup(
                self._group, _CONSUMER, {self._stream: ">"},
                count=1, block=int(timeout * 1000),
            )
        except ResponseError:
            await self._ensure_group()
            result = await self._redis.xreadgroup(
                self._group, _CONSUMER, {self._stream: ">"},
                count=1, block=int(timeout * 1000),
            )
        if not result:
            return None
        entry_id, fields = result[0][1][0]
        try:
            msg = BatchMessage.from_json(fields["payload"])
        except (KeyError, json.JSONDecodeError):
            await self._redis.xack(self._stream, self._group, entry_id)
            return None
        return QueuedJob(entry_id=entry_id, message=msg)

    async def ack(self, entry_id: str) -> None:
        """处理完成确认 — 从 pending 移除，不再重投。"""
        await self._redis.xack(self._stream, self._group, entry_id)

    async def nack(self, entry_id: str) -> None:
        """处理失败 — 读 body，attempts+1；超限进 DLQ，否则重投。"""
        try:
            raw = await self._redis.xrange(self._stream, min=entry_id, max=entry_id)
        except ResponseError:
            raw = []
        msg: BatchMessage | None = None
        if raw:
            try:
                msg = BatchMessage.from_json(raw[0][1]["payload"])
            except (KeyError, json.JSONDecodeError):
                msg = None
        await self._redis.xack(self._stream, self._group, entry_id)
        if msg is not None:
            msg.attempts += 1
            if msg.attempts > self._max_delivery:
                await self._xadd_dlq(msg)
            else:
                await self._redis.xadd(self._stream, {"payload": msg.to_json()})

    # ── batch 级并发控制（阶段 3）────────────────────────────

    async def acquire_lock(self, batch_id: str, ttl: int = 300) -> bool:
        """认领批锁（SET NX）——防双 worker / retry 与存活 worker 同批双跑。"""
        return bool(
            await self._redis.set(f"batch:{batch_id}:lock", "1", nx=True, ex=ttl)
        )

    async def release_lock(self, batch_id: str) -> None:
        await self._redis.delete(f"batch:{batch_id}:lock")

    async def renew_lock(self, batch_id: str, ttl: int = 300) -> None:
        """处理期间周期续租（防长批被可见性超时回收）。"""
        await self._redis.expire(f"batch:{batch_id}:lock", ttl)

    async def is_locked(self, batch_id: str) -> bool:
        return bool(await self._redis.exists(f"batch:{batch_id}:lock"))

    async def mark_superseded(self, batch_id: str, ttl: int = 7 * 24 * 3600) -> None:
        """标记批已被新提交取代（MinerU 重提交）——旧批消息回收后短路，不踩新状态。"""
        await self._redis.set(f"batch:{batch_id}:superseded", "1", ex=ttl)

    async def is_superseded(self, batch_id: str) -> bool:
        return bool(await self._redis.exists(f"batch:{batch_id}:superseded"))

    async def dead_letter(self, entry_id: str) -> None:
        """直接进 DLQ 并 ack 原消息。"""
        try:
            raw = await self._redis.xrange(self._stream, min=entry_id, max=entry_id)
            if raw:
                try:
                    msg = BatchMessage.from_json(raw[0][1]["payload"])
                    await self._xadd_dlq(msg)
                except (KeyError, json.JSONDecodeError):
                    pass
        except ResponseError:
            pass
        await self._redis.xack(self._stream, self._group, entry_id)
