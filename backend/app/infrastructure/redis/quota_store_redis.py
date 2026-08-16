"""额度记账 Redis 存储 — contract 4.2.2 三阶段语义。

```text
Redis Key:  quota:{key_id}:{date}        → 已用页数（整数，原子 INCR/DECR）
            reservation:{reservation_id} → {key_id, pages, state: reserved|committed|refunded}
语义：reserve(预占) → commit(仅 MinerU 提交成功) → refund(失败退回)
```

- `key_id` 用 token_id（`tk_N`）——**Redis 全程无明文 MinerU token**。
- 所有读-改-写操作走 Lua 脚本原子执行，跨进程（多 worker）一致（A-1.2）。
  Lua 脚本访问的 key 必须经 KEYS 传入（Redis 限制），故 commit/refund 由调用方
  携带 key_id/pages，配额 key 在 Python 侧按 `clock()` 计算后传入。
- `reservation:{id}` 带 TTL（默认 48h），防崩溃后泄漏。
- `clock` 可注入（T-1.8 跨日期重置测试）。
"""
from __future__ import annotations

import json
import time
from typing import Callable

_RESERVATION_TTL = 48 * 3600

# reserve: INCR 额度计数 + 写 reservation（带 TTL）
_LUA_RESERVE = """
local used = redis.call('INCRBY', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
return used
"""

# commit: reserved → committed（额度已在 reserve 时计入，此处不再动计数）
_LUA_COMMIT = """
local r = redis.call('GET', KEYS[1])
if not r then return 0 end
local d = cjson.decode(r)
if d.state == 'reserved' then
  d.state = 'committed'
  redis.call('SET', KEYS[1], cjson.encode(d), 'KEEPTTL')
  return 1
end
return 0
"""

# refund: reserved → refunded + DECR 当日计数（原子）
_LUA_REFUND = """
local r = redis.call('GET', KEYS[1])
if not r then return 0 end
local d = cjson.decode(r)
if d.state == 'reserved' then
  redis.call('DECRBY', KEYS[2], ARGV[1])
  d.state = 'refunded'
  redis.call('SET', KEYS[1], cjson.encode(d), 'KEEPTTL')
  return 1
end
return 0
"""


class QuotaStoreRedis:
    def __init__(self, redis, clock: Callable[[], str] | None = None):
        self._redis = redis
        self._clock = clock or (lambda: time.strftime("%Y-%m-%d"))

    def _quota_key(self, key_id: str) -> str:
        return f"quota:{key_id}:{self._clock()}"

    @staticmethod
    def _reservation_key(reservation_id: str) -> str:
        return f"reservation:{reservation_id}"

    async def reserve(self, key_id: str, pages: int, reservation_id: str) -> int:
        """预占额度：INCR 当日计数 + 写 reservation（reserved）。返回预占后已用页数。"""
        payload = json.dumps({"key_id": key_id, "pages": pages, "state": "reserved"})
        return await self._redis.eval(
            _LUA_RESERVE, 2,
            self._quota_key(key_id),
            self._reservation_key(reservation_id),
            pages, payload, _RESERVATION_TTL,
        )

    async def commit(self, reservation_id: str) -> bool:
        """仅 MinerU 提交成功后调用：reserved → committed（额度已在预占时计入）。"""
        return bool(
            await self._redis.eval(
                _LUA_COMMIT, 1, self._reservation_key(reservation_id)
            )
        )

    async def refund(self, key_id: str, pages: int, reservation_id: str) -> bool:
        """提交失败退回：reserved → refunded + DECR 当日计数（原子）。"""
        return bool(
            await self._redis.eval(
                _LUA_REFUND, 2,
                self._reservation_key(reservation_id),
                self._quota_key(key_id),
                pages,
            )
        )

    async def balance(self, key_id: str) -> int:
        """某 key 当日已用页数。"""
        raw = await self._redis.get(self._quota_key(key_id))
        return int(raw or 0)

    async def is_exhausted(self, key_ids: list[str], max_pages: int) -> bool:
        return bool(key_ids) and all(
            (await self.balance(kid)) >= max_pages for kid in key_ids
        )
