"""接口层共享 FastAPI 依赖。

- `get_container()`：DI 容器占位（阶段 1 由 AppContainer 实现，此处先提供惰性单例占位）。
- `require_kb_access()`：KB 作用域授权依赖。admin 透传；非 admin 需用户-KB 关联
  （关联模型在阶段 2 建模、阶段 4 在 chat/document service 落实强校验）。
  本阶段先提供机制并校验 KB 存在性，避免破坏现状非 admin 使用。
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.db import get_db
from src.models import KnowledgeBase, User


class _ContainerPlaceholder:
    """阶段 1 前的容器占位。阶段 1 替换为 infrastructure.container.AppContainer。"""

    def __getattr__(self, name: str):
        raise RuntimeError(
            f"AppContainer 尚未装配（阶段 1 落地）：{name}。"
            "请先完成阶段 1「基础设施归位与 DI 容器」。"
        )


_container: _ContainerPlaceholder | None = None


def get_container() -> _ContainerPlaceholder:
    """获取 DI 容器。阶段 1 前为占位；阶段 1 起返回 AppContainer 单例。"""
    global _container
    if _container is None:
        _container = _ContainerPlaceholder()
    return _container


async def require_kb_access(
    kb_id: uuid.UUID | None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """KB 作用域授权。

    规则：
    - `kb_id` 为 None → 未指定 KB（由调用方走默认 KB 逻辑），放行。
    - KB 不存在 → 404。
    - admin → 透传。
    - 非 admin → 阶段 4 前暂放行（无用户-KB 关联模型）；阶段 4 在此强校验归属。
    """
    if kb_id is None:
        return user

    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "知识库不存在")

    if user.role == "admin":
        return user

    # TODO(阶段4): 校验用户-KB 关联（用户-KB 成员关系建模后落实强校验）。
    return user
