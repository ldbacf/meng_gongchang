"""PostgreSQL 业务账本 — DocumentTask"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

PIPELINE_STEPS_ORDER = ["upload", "mineru", "chunking", "embedding", "es_write", "milvus"]


def default_pipeline_steps() -> dict:
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    return {s: {"status": "pending", "ts": now} for s in PIPELINE_STEPS_ORDER}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # 邮箱：管理端用户表格展示 + 搜索
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    # 封禁到期时间：NULL 表示未封禁或永久封禁（配合 enabled 判断）
    banned_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 最近活跃时间（管理端「活跃用户」排序用）
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="新对话", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rag_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    es_index: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    milvus_collection: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    documents: Mapped[list["DocumentTask"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class DocumentTask(Base):
    __tablename__ = "document_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    knowledge_base: Mapped[KnowledgeBase | None] = relationship(back_populates="documents")
    md5: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_minio_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    meta_minio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parsed_minio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING, nullable=False, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline_steps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ══════════════════════════════════════════════════════════════════
# 管理端：操作审计 + 检索埋点
# ══════════════════════════════════════════════════════════════════


class LogSeverity:
    """操作日志级别（与前端 severity 一一对应）"""

    INFO = "info"
    WARN = "warn"
    DANGER = "danger"
    SUCCESS = "success"


# action -> (中文显示名, 默认 severity)
OPERATION_ACTIONS: dict[str, tuple[str, str]] = {
    # 登录日志对全体用户生效，不限于管理员，因此标签不写「管理员」
    "auth.login": ("登录", LogSeverity.INFO),
    "auth.login_failed": ("登录失败", LogSeverity.WARN),
    "user.create": ("新建用户", LogSeverity.INFO),
    "user.ban": ("用户封禁", LogSeverity.DANGER),
    "user.unban": ("用户解封", LogSeverity.SUCCESS),
    "user.role_change": ("权限变更", LogSeverity.WARN),
    "user.delete": ("删除用户", LogSeverity.DANGER),
    "kb.create": ("知识库创建", LogSeverity.INFO),
    "kb.delete": ("知识库删除", LogSeverity.DANGER),
    "kb.import": ("知识库导入", LogSeverity.INFO),
    "doc.upload": ("文档上传", LogSeverity.INFO),
    "doc.delete": ("文档删除", LogSeverity.WARN),
    "doc.retry": ("文档重试", LogSeverity.INFO),
    "data.export": ("数据导出", LogSeverity.INFO),
    "system.config": ("系统配置", LogSeverity.WARN),
}


class OperationLog(Base):
    """操作审计日志。

    operator_name / operator_role 冗余存快照：用户被删后 operator_id 变 NULL，
    但日志仍可读。target_label 存人类可读描述，前端直接显示不用 join。
    """

    __tablename__ = "operation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    operator_role: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LogSeverity.INFO, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class RetrievalLog(Base):
    """检索埋点：知识库统计的唯一数据源。

    重要：预置文献（如「中国全科医学」1250 篇）由 scripts/import_es.py
    直接灌入 ES，从未在 document_tasks 建行。所以 citations.doc_id
    无法回溯到知识库 —— 统计只能靠这张表在检索发生时记录 kb_id。
    """

    __tablename__ = "retrieval_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    es_index: Mapped[str | None] = mapped_column(String(80), nullable=True)
    es_hits: Mapped[int] = mapped_column(default=0, nullable=False)
    milvus_hits: Mapped[int] = mapped_column(default=0, nullable=False)
    fused_count: Mapped[int] = mapped_column(default=0, nullable=False)
    cited_count: Mapped[int] = mapped_column(default=0, nullable=False)
    top_score: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    # is_hit 判定口径：cited_count > 0
    is_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
