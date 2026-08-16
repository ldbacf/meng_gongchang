"""
模型工厂 — 转发到 AppContainer（阶段 1，消除模块级单例）。

用法不变:
    from src.llm import get_chat_model, get_embedding_model

    chat = get_chat_model("deepseek-v4-flash")
    emb = get_embedding_model()
    emb_vec = emb.embed_query("高血压如何治疗")
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


def get_embedding_model(device: str = ""):
    """获取 bge-m3 嵌入模型（经容器唯一工厂，单例）。"""
    from app.interface.deps import get_container
    return get_container().get_embedder().get_hf_embeddings(device)


def get_sentence_transformer(device: str = ""):
    """获取原始 SentenceTransformer 实例（批量导入脚本兼容）。"""
    from app.interface.deps import get_container
    return get_container().get_embedder().get_sentence_transformer(device)
