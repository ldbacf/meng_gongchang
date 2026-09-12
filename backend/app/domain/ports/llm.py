"""LLM Chat 端口抽象 — LlmChatFactory 实现之。"""
from __future__ import annotations

from typing import Protocol


class LlmChatPort(Protocol):
    """大模型对话端口（同步 invoke；流式由具体实现提供）。"""

    def invoke(self, messages: list) -> object: ...
