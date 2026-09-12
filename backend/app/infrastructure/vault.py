"""TokenVault — MinerU token 与 token_id 的确定性映射。

队列 payload / Redis 额度 key 一律使用 token_id（`tk_1..tk_n`），
**明文 MinerU token 只经 `resolve()` 进 MinerU API 请求**，杜绝明文散落。

映射必须按 `Settings.mineru_token_list` 的**索引确定性构建**（而非运行时随机分配），
保证 API 进程与 worker 进程解析出的明文一致。
"""
from __future__ import annotations


class TokenVault:
    def __init__(self, tokens: list[str]):
        self._tokens = list(tokens)
        self._id_by_token: dict[str, str] = {
            t: f"tk_{i + 1}" for i, t in enumerate(self._tokens)
        }
        self._token_by_id: dict[str, str] = {
            v: k for k, v in self._id_by_token.items()
        }

    def __len__(self) -> int:
        return len(self._tokens)

    @property
    def token_ids(self) -> list[str]:
        return list(self._token_by_id.keys())

    def get_id(self, token: str) -> str | None:
        """明文 token → token_id（未知 token 返回 None，不抛异常）。"""
        return self._id_by_token.get(token)

    def resolve(self, token_id: str) -> str | None:
        """token_id → 明文 token（仅供 MinerU 请求调用）。"""
        return self._token_by_id.get(token_id)

    def first_id(self) -> str | None:
        """第一个可用 token_id（retry 等无上下文场景的兜底）。"""
        return self._token_by_id.keys().__iter__().__next__() if self._token_by_id else None

    def has(self, token_id: str) -> bool:
        return token_id in self._token_by_id
