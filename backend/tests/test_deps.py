"""interface 层依赖测试（阶段 0：容器占位机制）。"""
from __future__ import annotations

import pytest

from app.interface.deps import get_container


def test_container_placeholder_raises_until_phase1():
    c = get_container()
    with pytest.raises(RuntimeError, match="AppContainer 尚未装配"):
        c.es_client  # noqa: B018


def test_container_singleton():
    assert get_container() is get_container()
