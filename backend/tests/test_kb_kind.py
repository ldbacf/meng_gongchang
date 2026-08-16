"""T-2.5 — KBKind 策略解析：默认库→MEDICAL_DEFAULT；自定义→GENERIC；es_index/milvus_collection 解析。"""
from __future__ import annotations

from app.domain.knowledge_base import (
    DEFAULT_MEDICAL_SLUG,
    KBKind,
    KBPolicy,
    resolve_kb_kind,
)


class _FakeKB:
    def __init__(self, kb_kind=None, slug: str = ""):
        self.kb_kind = kb_kind
        self.slug = slug


def test_resolve_default_kb_medical():
    """默认期刊库（kb_kind=medical_default）→ MEDICAL_DEFAULT。"""
    assert resolve_kb_kind(_FakeKB(kb_kind="medical_default")) is KBKind.MEDICAL_DEFAULT


def test_resolve_generic_kb():
    """自定义库（kb_kind=generic）→ GENERIC。"""
    assert resolve_kb_kind(_FakeKB(kb_kind="generic")) is KBKind.GENERIC


def test_resolve_fallback_by_slug():
    """迁移前/脏数据：无 kb_kind 时按 slug 兜底判定。"""
    assert resolve_kb_kind(_FakeKB(kb_kind=None, slug=DEFAULT_MEDICAL_SLUG)) is KBKind.MEDICAL_DEFAULT
    assert resolve_kb_kind(_FakeKB(kb_kind=None, slug="my_kb")) is KBKind.GENERIC


def test_kb_policy_intent_strategy():
    assert KBPolicy(KBKind.GENERIC).is_generic is True
    assert KBPolicy(KBKind.GENERIC).intent_strategy == "generic"
    assert KBPolicy(KBKind.MEDICAL_DEFAULT).is_generic is False
    assert KBPolicy(KBKind.MEDICAL_DEFAULT).intent_strategy == "medical"


def test_kb_kind_values():
    assert KBKind.MEDICAL_DEFAULT.value == "medical_default"
    assert KBKind.GENERIC.value == "generic"
