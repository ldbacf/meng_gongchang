"""管理端路由 — 用户管理 + 文档管理 (admin only)"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import hash_password, require_admin
from src.db import get_db
from src.models import DocumentTask, User
from src.schemas import (
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── 用户管理 ────────────────────────────────────────────────


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [UserResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    req: UserCreateRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    req: UserUpdateRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")

    if req.enabled is not None:
        user.enabled = req.enabled
    if req.role is not None:
        user.role = req.role

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")
    if _admin.id == user.id:
        raise HTTPException(400, "不能删除自己")
    await db.delete(user)
    await db.commit()
    return {"ok": True}


# ── 文档管理 ────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DocumentTask).order_by(DocumentTask.created_at.desc()).limit(100)
    )
    tasks = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "md5": t.md5,
            "original_name": t.original_name,
            "status": t.status,
            "error_msg": t.error_msg,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in tasks
    ]


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DocumentTask).where(DocumentTask.id == doc_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "文档不存在")
    await db.delete(task)
    await db.commit()
    return {"ok": True}
