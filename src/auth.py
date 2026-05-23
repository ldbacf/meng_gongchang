"""JWT 鉴权模块 — 密码哈希 + Token 签发/验证 + FastAPI 依赖"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import (
    JWT_ACCESS_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_REFRESH_EXPIRE_DAYS,
    JWT_SECRET_KEY,
)
from src.db import get_db
from src.models import User

_SECRET = JWT_SECRET_KEY

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])


def get_token_remaining_ttl(token: str) -> int:
    """返回 token 剩余有效秒数，过期返回 0"""
    try:
        payload = decode_token(token)
        exp = payload.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        return max(0, int(exp - now))
    except JWTError:
        return 0


async def blacklist_token(token: str) -> None:
    """将 token 加入 Redis 黑名单，TTL 与 token 剩余有效期一致"""
    ttl = get_token_remaining_ttl(token)
    if ttl <= 0:
        return
    try:
        from src.redis_client import get_redis
        r = get_redis()
        await r.setex(f"blacklist:{token}", ttl, "1")
    except Exception:
        pass  # Redis 不可用时静默跳过


async def is_token_blacklisted(token: str) -> bool:
    try:
        from src.redis_client import get_redis
        r = get_redis()
        return await r.exists(f"blacklist:{token}") > 0
    except Exception:
        return False  # Redis 不可用时跳过黑名单检查


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """从 Bearer token 解析当前用户，校验 enabled 状态"""
    if credentials is None:
        raise HTTPException(401, "未提供认证凭证")

    token = credentials.credentials

    if await is_token_blacklisted(token):
        raise HTTPException(401, "Token 已失效")

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(401, "Token 无效或已过期")

    if payload.get("type") != "access":
        raise HTTPException(401, "Token 类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token 缺少用户标识")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "用户不存在")

    if not user.enabled:
        raise HTTPException(403, "账号已被禁用")

    return user


async def require_admin(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
