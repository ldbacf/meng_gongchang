"""问答生成端口 — 意图识别 / 查询扩展 / 回答生成。

节点只依赖本协议，不 import 具体适配器（DeepSeek / 硅基流动 等）。
实现见 `app/infrastructure/adapters/{query_intent,query_expansion,llm_answer}.py`。
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from app.domain.knowledge_base import KBKind
from app.domain.rag.intent import IntentResult


class IntentPort(Protocol):
    """意图识别 + 查询改写（同步，节点用 asyncio.to_thread 调用）。"""

    def analyze(
        self,
        query: str,
        last_context: str = "",
        kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
        timeout: float = 10.0,
    ) -> IntentResult:
        """失败时应返回空 IntentResult 而非抛错（降级由调用方判定）。"""
        ...


class QueryExpansionPort(Protocol):
    """口语 → 学术术语扩展（同步）。失败时返回原 query。"""

    def expand(self, query: str, timeout: float = 8.0) -> str: ...


class AnswerPort(Protocol):
    """回答生成（提示词构建 + 流式 token）。"""

    def build_prompt(
        self,
        query: str,
        hits: list,
        history: list[dict] | None = None,
        top_n: int = 5,
    ) -> str: ...

    def stream(
        self,
        user_prompt: str,
        kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """逐 token 产出；失败上抛（由 service 层产 t:error）。

        `system_prompt` 为空时按 `kb_kind` 选默认提示词。「直答」（意图判定为库外）
        传入 `DIRECT_SYSTEM_PROMPT`，覆盖默认的"只用文献回答"约束。
        """
        ...
