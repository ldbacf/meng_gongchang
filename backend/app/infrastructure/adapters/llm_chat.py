"""LLM Chat 单工厂 — 收敛旧 `src/llm.py::_CHAT_MODEL` 模块级单例。

- DeepSeek（OpenAI 兼容）；按 (model, temperature, streaming) 缓存实例。
- 实例由 AppContainer 持有，无模块级全局。
"""
from __future__ import annotations

from app.infrastructure.settings import Settings, get_settings


class LlmChatFactory:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._instances: dict[str, object] = {}

    def get_chat_model(
        self,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.0,
        streaming: bool = False,
        timeout: float = 60.0,
    ):
        """获取 DeepSeek Chat 模型实例（按参数缓存）。"""
        from langchain_openai import ChatOpenAI

        cache_key = f"{model}:{temperature}:{streaming}"
        inst = self._instances.get(cache_key)
        if inst is None:
            inst = ChatOpenAI(
                model=model,
                api_key=self._settings.deepseek_api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=temperature,
                streaming=streaming,
                timeout=timeout,
                max_retries=1,
            )
            self._instances[cache_key] = inst
        return inst

    def release(self) -> None:
        self._instances.clear()
