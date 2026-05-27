"""WebSocket 路由 — 文档状态实时推送到管理后台"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from src.auth import decode_token
from src.db import async_session
from src.models import User
from src.ws_manager import ws_manager

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

    await ws_manager.connect(websocket, kb_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_manager.disconnect(websocket, kb_id)
