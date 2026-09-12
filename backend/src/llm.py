"""模型工厂 — 转发到 AppContainer（阶段 1，消除模块级单例）。

用法不变:
    from src.llm import get_chat_model

    chat = get_chat_model("deepseek-v4-flash")
"""
from __future__ import annotations


def get_chat_model(
    model: str = "deepseek-v4-flash",
    temperature: float = 0.0,
    streaming: bool = False,
    timeout: float = 60.0,
):
    """获取 DeepSeek Chat 模型实例（经容器唯一工厂，按参数缓存）。"""
    from app.interface.deps import get_container
    return get_container().get_llm().get_chat_model(
        model=model, temperature=temperature, streaming=streaming, timeout=timeout,
    )
