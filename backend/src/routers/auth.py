"""鉴权路由 — 登录 / 刷新 / 登出 / 会话验证"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from src.db import get_db
from src.models import User
from src.schemas import (
    LoginRequest,
    RegisterRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    if not user.enabled:
        raise HTTPException(403, "账号已被禁用")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token)
    except Exception:
        raise HTTPException(401, "Refresh token 无效或已过期")

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Token 类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token 数据错误")

    from src.auth import is_token_blacklisted

    if await is_token_blacklisted(req.refresh_token):
        raise HTTPException(401, "Refresh token 已失效")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.enabled:
        raise HTTPException(401, "用户不存在或已禁用")

    await blacklist_token(req.refresh_token)

    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserResponse.model_validate(user),
    )


@router.post("/register")
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role="user",
        enabled=False,
    )
    db.add(user)
    await db.commit()

    return {"ok": True, "message": "注册成功，请等待管理员审核"}


@router.post("/logout")
async def logout(
    req: LogoutRequest,
    user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Security(
        HTTPBearer(auto_error=False)
    ),
):
    if credentials:
        await blacklist_token(credentials.credentials)
    if req.refresh_token:
        await blacklist_token(req.refresh_token)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    try:
        return UserResponse.model_validate(user)
    except Exception as e:
        raise HTTPException(500, f"model_validate failed: {e}")
