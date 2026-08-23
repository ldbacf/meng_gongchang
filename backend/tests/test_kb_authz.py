"""T-4.7 / T-4.9 / T-4.10 — KB 写边界 + 静态守卫。

- T-4.7：KB 写（上传/建库）admin-only → 非 admin 403；问答查询开放式，kb 不存在 → 404（无 403）。
- T-4.9：`search_with_intent`/`search_and_answer` 已从 src/ 移除（收敛进 QAGraph）。
- T-4.10：SSE 生成器不引用路由注入的长活 session（持久化用短会话）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.application.services.chat_service import ChatService
from app.infrastructure.container import AppContainer
from app.infrastructure.settings import Settings
from src.auth import require_admin


class _User:
    def __init__(self, role: str):
        self.id = uuid.uuid4()
        self.role = role


# ── T-4.7 ──────────────────────────────────────────────────────


async def test_admin_only_write_blocks_non_admin():
    with pytest.raises(HTTPException) as e:
        await require_admin(_User(role="user"))
    assert e.value.status_code == 403


async def test_admin_only_write_passthrough_admin():
    admin = _User(role="admin")
    assert await require_admin(admin) is admin


async def test_chat_query_kb_not_found_404():
    container = AppContainer(settings=Settings(_env_file=None, jwt_secret_key="x"))
    svc = ChatService(container)
    with pytest.raises(HTTPException) as e:
        await svc._resolve_kb(str(uuid.uuid4()))
    assert e.value.status_code == 404


# ── T-4.9 ──────────────────────────────────────────────────────


def test_deprecated_search_entry_removed():
    src_path = Path(__file__).resolve().parent.parent / "src" / "search.py"
    text = src_path.read_text(encoding="utf-8")
    assert "search_with_intent" not in text
    assert "search_and_answer" not in text


# ── T-4.10 ─────────────────────────────────────────────────────


def test_sse_generator_no_long_session():
    """SSE 生成器（ChatService._sse）不引用路由注入的长活 session。

    ChatService 持久化一律走 `get_container().get_db_sessionmaker()`（短会话），
    模块不 import `get_db`；persist 节点同理。
    """
    src_path = Path(__file__).resolve().parent.parent / "app" / "application" / "services" / "chat_service.py"
    text = src_path.read_text(encoding="utf-8")
    # 无路由注入的长活 session 依赖（不 import src.db.get_db / Depends(get_db)）
    assert "from src.db import get_db" not in text
    assert "Depends(get_db" not in text
    assert "async def get_db" not in text
    persist_path = (
        Path(__file__).resolve().parent.parent / "app" / "application" / "graphs" / "rag" / "nodes" / "persist.py"
    )
    assert "get_db_sessionmaker()" in persist_path.read_text(encoding="utf-8")
