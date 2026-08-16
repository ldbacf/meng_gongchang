"""bge-m3 嵌入模型唯一工厂 — 收敛旧 `src/llm.py` 与 `scripts/import_milvus.py` 的多份单例。

- 本地 `backend/models/bge-m3/` 优先，否则回退 `BAAI/bge-m3`。
- `get_hf_embeddings()`：LangChain HuggingFaceEmbeddings（在线 query 嵌入）。
- `get_sentence_transformer()`：原始 SentenceTransformer（批量编码脚本）。
- 两种包装各自实例化一次并缓存（同一底层模型），生命周期由 AppContainer 管理。
"""
from __future__ import annotations

import os
from pathlib import Path

_MODEL_SUBDIR = "models" / Path("bge-m3")


class EmbeddingFactory:
    def __init__(self, models_dir: str | None = None):
        # models_dir: 显式模型目录（测试可注入）；默认 backend/models/
        self._models_dir = models_dir
        self._hf: object | None = None
        self._st: object | None = None

    def _model_path(self) -> str:
        base = self._models_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent / "models"
        )
        local = os.path.abspath(os.path.join(base, "bge-m3"))
        return local if os.path.isdir(local) else "BAAI/bge-m3"

    def get_hf_embeddings(self, device: str = ""):
        """LangChain HuggingFaceEmbeddings（query 嵌入），单例。"""
        if self._hf is None:
            from langchain_huggingface import HuggingFaceEmbeddings

            model_kwargs = {"device": device} if device else {}
            self._hf = HuggingFaceEmbeddings(
                model_name=self._model_path(),
                model_kwargs=model_kwargs,
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._hf

    def get_sentence_transformer(self, device: str = ""):
        """原始 SentenceTransformer（批量编码），单例。"""
        if self._st is None:
            from sentence_transformers import SentenceTransformer

            kw = {"device": device} if device else {}
            self._st = SentenceTransformer(self._model_path(), **kw)
        return self._st

    def release(self) -> None:
        """释放模型引用（close 时调用）。"""
        self._hf = None
        self._st = None
