"""知识库策略 — KBKind 显式化。

`slug == "zhong_guo_quan_ke"` 过去承担「默认期刊库 + is_generic」双重隐性语义，
现由 `kb_kind` 字段显式承载：
- MEDICAL_DEFAULT：默认《中国全科医学》期刊库（检索/回答用期刊 prompt，走离线切分）。
- GENERIC：用户自定义通用知识库（在线自动索引，用通用 prompt）。

slug 仅作为 seed 展示标识保留（main.py 创建默认库、迁移回填），分支判断一律用 kb_kind。
纯 stdlib，零外部依赖。
"""
from __future__ import annotations

from enum import Enum

# 默认期刊库的 seed 标识（仅 seed/迁移使用，业务分支判断改用 KBKind）
DEFAULT_MEDICAL_SLUG = "zhong_guo_quan_ke"


class KBKind(str, Enum):
    MEDICAL_DEFAULT = "medical_default"
    GENERIC = "generic"


class KBPolicy:
    """KBKind → 意图策略 / prompt 档位（es_index/milvus_collection 由 ORM 字段承载）。"""

    def __init__(self, kb_kind: KBKind):
        self.kb_kind = kb_kind

    @property
    def is_generic(self) -> bool:
        return self.kb_kind is KBKind.GENERIC

    @property
    def intent_strategy(self) -> str:
        return "generic" if self.is_generic else "medical"


def resolve_kb_kind(kb) -> KBKind:
    """从 KnowledgeBase 对象解析 KBKind。

    优先读 `kb.kb_kind` 字段（迁移后为真源）；兜底按 slug 判定（迁移前/脏数据）。
    """
    raw = getattr(kb, "kb_kind", None)
    if raw:
        try:
            return KBKind(raw)
        except ValueError:
            pass
    slug = getattr(kb, "slug", "") or ""
    return KBKind.MEDICAL_DEFAULT if slug == DEFAULT_MEDICAL_SLUG else KBKind.GENERIC
