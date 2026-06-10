"""
模型工厂 — 统一管理所有 LangChain 模型实例。

用法:
    from src.llm import get_chat_model, get_embedding_model

    chat = get_chat_model("deepseek-v4-flash")
    emb = get_embedding_model()
    emb_vec = emb.embed_query("高血压如何治疗")
"""

from __future__ import annotations

import os

from src.config import DEEPSEEK_API_KEY, SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_RERANK_MODEL


# ═══════════════════════════════════════════════════════════════
# Chat Model — DeepSeek (OpenAI 兼容)
# ═══════════════════════════════════════════════════════════════

_CHAT_MODEL = None
_CHAT_MODEL_ID = ""


def get_chat_model(
    model: str = "deepseek-v4-flash",
    temperature: float = 0.0,
    streaming: bool = False,
    timeout: float = 60.0,
) -> "ChatOpenAI":
    """获取 DeepSeek Chat 模型实例（模块级单例，model 变化时重建）"""
    global _CHAT_MODEL, _CHAT_MODEL_ID

    cache_key = f"{model}:{temperature}:{streaming}"
    if _CHAT_MODEL is None or _CHAT_MODEL_ID != cache_key:
        from langchain_openai import ChatOpenAI

        _CHAT_MODEL = ChatOpenAI(
            model=model,
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com/v1",
            temperature=temperature,
            streaming=streaming,
            timeout=timeout,
            max_retries=1,
        )
        _CHAT_MODEL_ID = cache_key
    return _CHAT_MODEL


# ═══════════════════════════════════════════════════════════════
# Embedding Model — bge-m3 (本地优先)
# ═══════════════════════════════════════════════════════════════

_EMBED_MODEL = None


def get_embedding_model(device: str = "") -> "HuggingFaceEmbeddings":
    """获取 bge-m3 嵌入模型（模块级单例，优先本地 models/bge-m3/）"""
    global _EMBED_MODEL

    if _EMBED_MODEL is None:
        from langchain_huggingface import HuggingFaceEmbeddings

        local = os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
        local = os.path.abspath(local)
        model_name = local if os.path.isdir(local) else "BAAI/bge-m3"
        model_kwargs = {"device": device} if device else {}
        _EMBED_MODEL = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _EMBED_MODEL


# ═══════════════════════════════════════════════════════════════
# (向下兼容) raw SentenceTransformer 实例 — 仅 import_milvus.py 等脚本使用
# ═══════════════════════════════════════════════════════════════

_RAW_ST_MODEL = None


def get_sentence_transformer(device: str = ""):
    """获取原始 SentenceTransformer 实例（向后兼容批量导入脚本）。"""
    global _RAW_ST_MODEL

    if _RAW_ST_MODEL is None:
        from sentence_transformers import SentenceTransformer

        local = os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
        local = os.path.abspath(local)
        model_id = local if os.path.isdir(local) else "BAAI/bge-m3"
        kw = {"device": device} if device else {}
        _RAW_ST_MODEL = SentenceTransformer(model_id, **kw)
    return _RAW_ST_MODEL
