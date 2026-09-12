"""interface 层依赖测试（AppContainer 单例）。"""
from __future__ import annotations

from app.interface.deps import get_container, set_container
from app.infrastructure.container import AppContainer


def test_container_is_appcontainer():
    assert isinstance(get_container(), AppContainer)


def test_container_singleton():
    assert get_container() is get_container()


def test_set_container_reset():
    """测试可替换容器；重置为 None 后惰性重建。"""
    fresh = AppContainer()
    set_container(fresh)
    try:
        assert get_container() is fresh
    finally:
        set_container(None)
    assert get_container() is not fresh
