"""多 Key 额度管理与自动轮换

用法:
    manager = get_key_manager()
    token = manager.acquire(pdf_pages)
    manager.release(token, pdf_pages)   # 提交成功后扣除额度
    manager.usage_report()              # 查看各 key 日用量
"""

import os
import time
from datetime import date

# 从 .env 读取，避免循环导入
_TOKENS_ENV = (os.getenv("MINERU_TOKENS") or os.getenv("MINERU_API_TOKEN") or "")
if "," in _TOKENS_ENV:
    ALL_TOKENS = [t.strip() for t in _TOKENS_ENV.split(",") if t.strip()]
elif _TOKENS_ENV:
    ALL_TOKENS = [_TOKENS_ENV]
else:
    ALL_TOKENS = []

MAX_PAGES_PER_KEY = int(os.getenv("MINERU_MAX_PAGES_PER_KEY", "1000"))
BATCH_SIZE = int(os.getenv("MINERU_BATCH_SIZE", "10"))


class TokenExhausted(Exception):
    """所有 token 当日额度均已用完"""


class KeyManager:
    """额度管理器 — Best-fit 分配（选剩余最接近但不浪费的 key）"""

    def __init__(self, tokens: list[str], max_pages: int):
        self._tokens = tokens[:]
        self._max_pages = max_pages
        self._usage: dict[str, dict] = {t: {"used": 0, "date": str(date.today())} for t in tokens}

    def _today(self) -> str:
        return str(date.today())

    def _check_reset(self):
        """每日自动重置"""
        today = self._today()
        for t in self._tokens:
            if self._usage[t]["date"] != today:
                self._usage[t] = {"used": 0, "date": today}

    def remaining(self, token: str) -> int:
        """某 key 剩余页数"""
        self._check_reset()
        return max(0, self._max_pages - self._usage[token]["used"])

    def acquire(self, pages_needed: int) -> str:
        """
        Best-fit 分配: 找剩余额度最接近 pages_needed 的 key，
        避免大 key 被小文件碎片化。
        """
        self._check_reset()
        if not self._tokens:
            raise RuntimeError("没有配置任何 API Token")

        best = None
        best_remain = 999999
        for t in self._tokens:
            rem = self.remaining(t)
            if rem >= pages_needed and rem < best_remain:
                best = t
                best_remain = rem

        if best is not None:
            return best

        raise TokenExhausted(
            f"所有 Token 当日额度已用完 (max={self._max_pages}/key)\n"
            + self.usage_report()
        )

    def release(self, token: str, pages: int):
        """提交成功后，扣除额度"""
        self._check_reset()
        if token in self._usage:
            self._usage[token]["used"] += pages

    def usage_report(self) -> str:
        """格式化各 key 用量"""
        self._check_reset()
        lines = []
        for t in self._tokens:
            used = self._usage[t]["used"]
            remain = self._max_pages - used
            mask = t[:8] + "..." + t[-4:] if len(t) > 16 else t
            lines.append(f"  {mask}: {used}/{self._max_pages} (剩余{remain})")
        return "\n".join(lines)

    def is_exhausted(self) -> bool:
        """所有 key 都满了吗"""
        return len(self._tokens) > 0 and all(
            self.remaining(t) < 1 for t in self._tokens
        )


# ── 全局单例 ──────────────────────────────────────────────
_manager: KeyManager | None = None


def get_key_manager() -> KeyManager:
    global _manager
    if _manager is None:
        if not ALL_TOKENS:
            raise RuntimeError(
                "未配置 MinerU Token。请设置 MINERU_TOKENS 或 MINERU_API_TOKEN"
            )
        _manager = KeyManager(ALL_TOKENS, MAX_PAGES_PER_KEY)
        print(f"[KeyManager] 已加载 {len(ALL_TOKENS)} 个 Token, "
              f"每 key 日限额 {MAX_PAGES_PER_KEY} 页, "
              f"每批 {BATCH_SIZE} 个文件")
    return _manager
