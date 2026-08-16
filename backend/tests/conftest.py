"""pytest 共享 fixture。

阶段 0 以契约/纯函数单测为主（不依赖真实外部服务）；
阶段 1 起在此扩展 fakeredis / testcontainers fixture（ES/Milvus/Redis/PG）。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

TEST_JWT_SECRET = "pytest-test-secret"


@contextmanager
def env(**kwargs: str | None) -> Iterator[None]:
    """临时设置环境变量（None 表示删除）。"""
    saved = {}
    try:
        for k, v in kwargs.items():
            saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def env_ctx() -> Any:
    return env
