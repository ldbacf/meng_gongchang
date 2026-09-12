"""WebSocket 路由 — 文档状态实时推送到管理后台"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.interface.security import decode_token
from app.infrastructure.db.session import async_session
from app.infrastructure.db.models import User
from app.infrastructure.ws_manager import get_ws_registry

router = APIRouter()


@router.websocket("/api/v1/ws/documents/{kb_id}")
async def ws_documents(
    websocket: WebSocket,
    kb_id: str,
    token: str = Query(...),
):
    # JWT 验证
    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 黑名单校验（登出后 token 立即失效）
    from app.interface.security import is_token_blacklisted

    if await is_token_blacklisted(token):
        await websocket.close(code=4001, reason="Token revoked")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Missing user")
        return

    if payload.get("type") != "access":
        await websocket.close(code=4001, reason="Token type error")
        return

    # 查用户
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.enabled:
            await websocket.close(code=4003, reason="User disabled or not found")
            return
        if user.role != "admin":
            await websocket.close(code=4003, reason="Admin only")
            return

    ws_registry = get_ws_registry()
    await ws_registry.connect(websocket, kb_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_registry.disconnect(websocket, kb_id)
