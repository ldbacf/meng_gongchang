"""操作审计 + 检索埋点。

设计原则：
1. 两个写入口（log_operation / log_retrieval）**各自开独立 session**，
   绝不污染调用方的事务 —— 日志失败不能让封禁/删除等业务回滚。
2. 全部异常吞掉，只记 logger.warning。
"""

import logging
import uuid
from datetime import datetime, timezone

from src.db import async_session
from src.models import LogSeverity, OPERATION_ACTIONS, OperationLog, RetrievalLog

logger = logging.getLogger(__name__)

# action -> 中文显示名（供接口翻译）
ACTION_LABELS: dict[str, str] = {k: v[0] for k, v in OPERATION_ACTIONS.items()}


def get_client_ip(request) -> str | None:
    """取真实客户端 IP：反向代理下优先 X-Forwarded-For。"""
    if request is None:
        return None
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()[:45]
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()[:45]
        return request.client.host if request.client else None
    except Exception:
        return None


async def log_operation(
    *,
    operator,
    action: str,
    severity: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    target_label: str | None = None,
    detail: str | None = None,
    request=None,
) -> None:
    """写一条操作日志。**永不抛异常。**

    operator 可以是 User 对象，也可以是 None（系统操作）。
    severity 为 None 时按 OPERATION_ACTIONS 的默认档位。
    """
    try:
        _, default_sev = OPERATION_ACTIONS.get(action, (action, LogSeverity.INFO))
        async with async_session() as session:
            session.add(
                OperationLog(
                    operator_id=getattr(operator, "id", None),
                    operator_name=getattr(operator, "username", None) or "system",
                    operator_role=getattr(operator, "role", None) or "system",
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    target_label=(target_label or "")[:512] or None,
                    detail=detail,
                    ip=get_client_ip(request),
                    severity=severity or default_sev,
                )
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001 — 日志失败绝不影响主流程
        logger.warning("写操作日志失败 action=%s: %s", action, e)


async def log_retrieval(
    *,
    user_id: uuid.UUID | None,
    kb_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    query: str | None = None,
    es_index: str | None = None,
    es_hits: int = 0,
    milvus_hits: int = 0,
    fused_count: int = 0,
    cited_count: int = 0,
    top_score: float | None = None,
    latency_ms: int | None = None,
) -> None:
    """写一条检索埋点。**永不抛异常。**"""
    try:
        async with async_session() as session:
            session.add(
                RetrievalLog(
                    user_id=user_id,
                    kb_id=kb_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    query=(query or "")[:4000] or None,
                    es_index=es_index,
                    es_hits=es_hits,
                    milvus_hits=milvus_hits,
                    fused_count=fused_count,
                    cited_count=cited_count,
                    top_score=top_score,
                    latency_ms=latency_ms,
                    is_hit=cited_count > 0,
                )
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("写检索埋点失败 kb_id=%s: %s", kb_id, e)


async def touch_user_activity(user_id: uuid.UUID | None) -> None:
    """更新 users.last_active_at。永不抛异常。"""
    if not user_id:
        return
    try:
        from sqlalchemy import update

        from src.models import User

        async with async_session() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(last_active_at=datetime.now(timezone.utc))
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("更新活跃时间失败 user_id=%s: %s", user_id, e)
