"""接口层共享 FastAPI 依赖。

- `get_container()`：进程级 AppContainer 单例（lazy 创建，无客户端实例化副作用）。
- `set_container()`：测试替换容器（注入 fake 客户端）。
- `require_kb_access()`：KB 作用域授权依赖。admin 透传；非 admin 需用户-KB 关联
  （关联模型在阶段 2 建模、阶段 4 在 chat/document service 落实强校验）。
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.db import get_db
from src.models import KnowledgeBase, User

from app.infrastructure.container import AppContainer

_container: AppContainer | None = None


def get_container() -> AppContainer:
    """获取进程级 DI 容器单例。"""
    global _container
    if _container is None:
        _container = AppContainer()
    return _container


def set_container(container: AppContainer | None) -> None:
    """测试专用：替换进程级容器单例（传 None 重置为惰性重建）。"""
    global _container
    _container = container


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
