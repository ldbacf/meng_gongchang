"""管理端统计接口 — 用户指标 / 活跃用户 / 知识库统计 / 操作日志。

全部需要 admin 权限。数据源：
- 用户相关：users / conversations / messages / retrieval_logs
- 知识库统计：retrieval_logs（唯一数据源，见 models.RetrievalLog 注释）
- 操作日志：operation_logs

时区约定：所有"今天/按天"的口径都按 **Asia/Shanghai** 计算，
不依赖数据库会话时区（容器默认 UTC）。
"""

import zoneinfo
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.db import get_db
from src.log_service import ACTION_LABELS
from src.schemas import (
    ActiveMetrics,
    ActiveUserItem,
    ActiveUserListResponse,
    AdminUserItem,
    AdminUserListResponse,
    KbRankItem,
    KbStatsMetrics,
    KbStatsResponse,
    KbTrendPoint,
    LogMetrics,
    OperationLogItem,
    OperationLogListResponse,
    UserMetrics,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-stats"])

LOCAL_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def _now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def _start_of_today_utc() -> datetime:
    """今天 00:00（上海）对应的 UTC 时刻。"""
    local = _now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def _since_utc(days: int) -> datetime:
    """最近 N 天（含今天）起点，按上海时区的自然日。"""
    local = _now_local() - timedelta(days=days - 1)
    local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


# ══════════════════════════════════════════════════════════════
# A1 · 用户列表（分页 + 搜索 + 筛选）
# ══════════════════════════════════════════════════════════════


@router.get("/users", response_model=AdminUserListResponse)
async def list_users_paged(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="匹配用户名或邮箱"),
    status: str = Query("all", pattern="^(all|active|banned|pending)$"),
    role: str = Query("all", pattern="^(all|admin|user)$"),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """用户列表。

    status 三态语义（注意 register 默认 enabled=False 表示待审核）：
      active  -> enabled = true
      banned  -> enabled = false 且 banned_until 非空（真的被封禁）
      pending -> enabled = false 且 banned_until 为空（待审核/被禁用）
    """
    where: list[str] = []
    params: dict = {}

    if search:
        where.append("(u.username ILIKE :kw OR u.email ILIKE :kw)")
        params["kw"] = f"%{search}%"
    if role != "all":
        where.append("u.role = :role")
        params["role"] = role
    if status == "active":
        where.append("u.enabled = true")
    elif status == "banned":
        where.append("u.enabled = false AND u.banned_until IS NOT NULL")
    elif status == "pending":
        where.append("u.enabled = false AND u.banned_until IS NULL")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = (
        await db.execute(
            text(f"SELECT count(*) FROM users u {where_sql}"), params
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            text(
                f"""
                SELECT
                    u.id, u.username, u.email, u.role, u.enabled, u.banned_until,
                    u.last_login, u.created_at,
                    COALESCE(c.conv_count, 0)  AS chats,
                    COALESCE(r.hit_count, 0)   AS kb_calls
                FROM users u
                LEFT JOIN (
                    SELECT user_id, count(*) AS conv_count
                    FROM conversations GROUP BY user_id
                ) c ON c.user_id = u.id
                LEFT JOIN (
                    SELECT user_id, count(*) AS hit_count
                    FROM retrieval_logs WHERE is_hit = true GROUP BY user_id
                ) r ON r.user_id = u.id
                {where_sql}
                ORDER BY u.created_at ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
    ).mappings().all()

    items = []
    for r in rows:
        if r["enabled"]:
            st = "正常"
        elif r["banned_until"] is not None:
            st = "已封禁"
        else:
            st = "待审核"
        items.append(
            AdminUserItem(
                id=r["id"],
                username=r["username"],
                email=r["email"],
                role=r["role"],
                enabled=r["enabled"],
                status=st,
                chats=r["chats"],
                kbCalls=r["kb_calls"],
                lastLogin=r["last_login"],
                registeredAt=r["created_at"],
            )
        )

    return AdminUserListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


# ══════════════════════════════════════════════════════════════
# A2 · 用户指标卡
# ══════════════════════════════════════════════════════════════


@router.get("/users/metrics", response_model=UserMetrics)
async def user_metrics(
    _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    row = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)                                                        AS total,
                    count(*) FILTER (WHERE enabled = true)                          AS normal,
                    count(*) FILTER (WHERE enabled = false
                                       AND banned_until IS NOT NULL)                AS banned,
                    count(*) FILTER (WHERE created_at >= :today)                    AS today_new
                FROM users
                """
            ),
            {"today": _start_of_today_utc()},
        )
    ).mappings().one()

    return UserMetrics(
        total=row["total"],
        normal=row["normal"],
        banned=row["banned"],
        todayNew=row["today_new"],
    )


# ══════════════════════════════════════════════════════════════
# A3 / A4 · 活跃用户
# ══════════════════════════════════════════════════════════════


@router.get("/active-users", response_model=ActiveUserListResponse)
async def active_users(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """活跃用户排行。

    口径（与前端注释一致）：
      sessions   = 窗口内产生过消息的会话数
      chats      = 窗口内 role='ai' 的消息数
      lastActive = 窗口内最后一条消息时间
      kbCalls    = 窗口内命中的检索次数（is_hit）
      score      = chats + kbCalls * 2
    """
    since = _since_utc(days)
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    u.id            AS user_id,
                    u.username      AS name,
                    u.email         AS email,
                    COALESCE(c.sessions, 0)   AS sessions,
                    COALESCE(m.chats, 0)      AS chats,
                    COALESCE(r.kb_calls, 0)   AS kb_calls,
                    m.last_active             AS last_active
                FROM users u
                LEFT JOIN (
                    SELECT c2.user_id, count(DISTINCT c2.id) AS sessions
                    FROM conversations c2
                    JOIN messages m2 ON m2.conversation_id = c2.id
                    WHERE m2.created_at >= :since
                    GROUP BY c2.user_id
                ) c ON c.user_id = u.id
                LEFT JOIN (
                    SELECT c3.user_id, count(*) FILTER (WHERE m3.role = 'ai') AS chats,
                           max(m3.created_at) AS last_active
                    FROM conversations c3
                    JOIN messages m3 ON m3.conversation_id = c3.id
                    WHERE m3.created_at >= :since
                    GROUP BY c3.user_id
                ) m ON m.user_id = u.id
                LEFT JOIN (
                    SELECT user_id, count(*) AS kb_calls
                    FROM retrieval_logs
                    WHERE is_hit = true AND created_at >= :since
                    GROUP BY user_id
                ) r ON r.user_id = u.id
                WHERE u.enabled = true
                  AND (COALESCE(c.sessions, 0) > 0 OR COALESCE(r.kb_calls, 0) > 0)
                ORDER BY (COALESCE(m.chats, 0) + COALESCE(r.kb_calls, 0) * 2) DESC,
                         COALESCE(m.last_active, u.created_at) DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
    ).mappings().all()

    items = [
        ActiveUserItem(
            userId=r["user_id"],
            name=r["name"],
            email=r["email"],
            chats=r["chats"],
            kbCalls=r["kb_calls"],
            sessions=r["sessions"],
            lastActive=r["last_active"],
            score=float(r["chats"] + r["kb_calls"] * 2),
        )
        for r in rows
    ]
    return ActiveUserListResponse(items=items)


@router.get("/active-users/metrics", response_model=ActiveMetrics)
async def active_metrics(
    _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    today = _start_of_today_utc()
    row = (
        await db.execute(
            text(
                """
                SELECT
                    (SELECT count(DISTINCT c.user_id)
                       FROM conversations c JOIN messages m ON m.conversation_id = c.id
                      WHERE m.created_at >= :since)                 AS active_users,
                    (SELECT count(DISTINCT c.user_id)
                       FROM conversations c JOIN messages m ON m.conversation_id = c.id
                      WHERE m.created_at >= :today)                 AS today_active,
                    (SELECT count(*) FROM retrieval_logs
                      WHERE is_hit = true)                          AS kb_calls,
                    (SELECT COALESCE(round(avg(cnt)::numeric, 1), 0)
                       FROM (SELECT count(*)::numeric AS cnt
                               FROM messages m2
                               JOIN conversations c2 ON c2.id = m2.conversation_id
                              WHERE m2.role = 'ai'
                              GROUP BY c2.user_id) t)               AS avg_chats
                """
            ),
            {"since": _since_utc(7), "today": today},
        )
    ).mappings().one()

    return ActiveMetrics(
        activeUsers=row["active_users"],
        todayActive=row["today_active"],
        kbCalls=row["kb_calls"],
        avgChats=float(row["avg_chats"] or 0),
    )


# ══════════════════════════════════════════════════════════════
# A5 · 知识库统计
# ══════════════════════════════════════════════════════════════


@router.get("/knowledge-stats", response_model=KbStatsResponse)
async def knowledge_stats(
    days: int = Query(7, ge=1, le=90),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    since = _since_utc(days)
    today = _start_of_today_utc()

    total_entries = (
        await db.execute(text("SELECT count(*) FROM document_tasks"))
    ).scalar() or 0

    agg = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)                                          AS total_calls,
                    count(*) FILTER (WHERE created_at >= :today)      AS today_calls,
                    count(*) FILTER (WHERE is_hit = true)             AS hits
                FROM retrieval_logs
                WHERE created_at >= :since
                """
            ),
            {"since": since, "today": today},
        )
    ).mappings().one()

    total_calls = agg["total_calls"] or 0
    hit_rate = round((agg["hits"] or 0) / total_calls, 4) if total_calls else 0.0

    # ── 趋势：按上海时区的自然日分组，缺失日期补 0 ──
    ts_rows = (
        await db.execute(
            text(
                "SELECT created_at FROM retrieval_logs WHERE created_at >= :since"
            ),
            {"since": since},
        )
    ).scalars().all()

    counter: Counter[str] = Counter()
    for ts in ts_rows:
        counter[ts.astimezone(LOCAL_TZ).date().isoformat()] += 1

    trend: list[KbTrendPoint] = []
    for i in range(days):
        day = (_now_local() - timedelta(days=days - 1 - i)).date().isoformat()
        trend.append(KbTrendPoint(day=day, value=counter.get(day, 0)))

    # ── 排行：按知识库统计命中调用次数 ──
    rank_rows = (
        await db.execute(
            text(
                """
                SELECT kb.name AS title, kb.es_index AS tag, count(rl.id) AS calls
                FROM retrieval_logs rl
                JOIN knowledge_bases kb ON kb.id = rl.kb_id
                WHERE rl.created_at >= :since
                GROUP BY kb.id, kb.name, kb.es_index
                ORDER BY calls DESC
                LIMIT 10
                """
            ),
            {"since": since},
        )
    ).mappings().all()

    ranks = [
        KbRankItem(title=r["title"], tag=r["tag"] or "", calls=r["calls"])
        for r in rank_rows
    ]

    return KbStatsResponse(
        metrics=KbStatsMetrics(
            totalEntries=total_entries,
            totalCalls=total_calls,
            todayCalls=agg["today_calls"] or 0,
            hitRate=hit_rate,
        ),
        trend=trend,
        ranks=ranks,
    )


# ══════════════════════════════════════════════════════════════
# A6 / A7 · 操作日志
# ══════════════════════════════════════════════════════════════


@router.get("/operation-logs", response_model=OperationLogListResponse)
async def operation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: str = Query("", description="action 键或中文名，如 user.ban / 用户封禁"),
    severity: str = Query("", description="info|warn|danger|success，逗号分隔"),
    q: str = Query("", description="匹配操作人/对象/详情/IP"),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    where: list[str] = []
    params: dict = {}

    if type:
        # 支持传 action 键或中文显示名
        if type in ACTION_LABELS:
            where.append("action = :action")
            params["action"] = type
        else:
            matched = [k for k, v in ACTION_LABELS.items() if v == type]
            if matched:
                where.append("action = ANY(:actions)")
                params["actions"] = matched
            else:
                where.append("action = :action")
                params["action"] = type

    if severity:
        sevs = [s.strip() for s in severity.split(",") if s.strip()]
        if sevs:
            where.append("severity = ANY(:sevs)")
            params["sevs"] = sevs

    if q:
        where.append(
            "(operator_name ILIKE :kw OR target_label ILIKE :kw "
            "OR detail ILIKE :kw OR ip ILIKE :kw)"
        )
        params["kw"] = f"%{q}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = (
        await db.execute(
            text(f"SELECT count(*) FROM operation_logs {where_sql}"), params
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, operator_name, operator_role, action, target_label,
                       detail, ip, severity, created_at
                FROM operation_logs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
    ).mappings().all()

    items = [
        OperationLogItem(
            id=r["id"],
            time=r["created_at"],
            operatorName=r["operator_name"],
            operatorRole=r["operator_role"],
            type=ACTION_LABELS.get(r["action"], r["action"]),
            action=r["action"],
            target=r["target_label"],
            detail=r["detail"],
            ip=r["ip"],
            severity=r["severity"],
        )
        for r in rows
    ]

    return OperationLogListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("/operation-logs/metrics", response_model=LogMetrics)
async def operation_log_metrics(
    _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    today = _start_of_today_utc()
    online_since = datetime.now(timezone.utc) - timedelta(minutes=15)

    row = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)                                                       AS total,
                    count(*) FILTER (WHERE created_at >= :today)                   AS today,
                    count(*) FILTER (WHERE severity IN ('warn','danger'))          AS risky,
                    count(DISTINCT operator_id) FILTER (
                        WHERE created_at >= :online_since
                          AND operator_role = 'admin'
                          AND operator_id IS NOT NULL)                             AS admin_online
                FROM operation_logs
                """
            ),
            {"today": today, "online_since": online_since},
        )
    ).mappings().one()

    return LogMetrics(
        total=row["total"],
        today=row["today"],
        risky=row["risky"],
        adminOnline=row["admin_online"] or 0,
    )
