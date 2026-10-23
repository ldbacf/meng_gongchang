"""接口层共享 FastAPI 依赖。

- `get_container()` / `set_container()`：**从 infrastructure 层 re-export**。
  容器是各层共用的装配根，单例定义在 `app/infrastructure/container.py`——放在这里会让
  application / infrastructure 反向 import interface，分层被打穿。此处的 re-export 只为
  让接口层内部与既有测试保持 `from app.interface.deps import get_container` 可用；
  **新代码请直接从 `app.infrastructure.container` 导入**。
- `require_kb_access()`：KB 作用域授权依赖——校验 KB 存在（不存在→404）；
  查询对所有登录用户开放（未引入 KB 归属模型）；写操作（上传/建库）由 `require_admin` 把关。
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.interface.security import get_current_user
from app.infrastructure.db.session import get_db
from app.infrastructure.db.models import KnowledgeBase, User

# re-export：容器单例真源在 infrastructure 层（理由见模块 docstring）
from app.infrastructure.container import (  # noqa: F401
    AppContainer,
    get_container,
    set_container,
)


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
    - 非 admin → 放行（查询对所有登录用户开放；KB 归属模型未引入）。
    """
    if kb_id is None:
        return user

    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "知识库不存在")

    if user.role == "admin":
        return user

    # 注：未引入用户-KB 归属模型，故查询侧不做归属校验；写操作由 require_admin 把关。
    return user
