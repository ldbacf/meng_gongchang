"""
Reranker 封装 — 转发到 app.infrastructure.adapters.rerank（阶段 1）。

旧 `src/reranker.py` 的类与工厂迁移至基础设施层（读 Settings 而非模块级常量），
本模块保留导出名以兼容残留 import。
"""
from __future__ import annotations

from app.infrastructure.adapters.rerank import SiliconFlowReranker, get_reranker  # noqa: F401
