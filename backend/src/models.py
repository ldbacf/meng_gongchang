"""PostgreSQL 业务账本 — DocumentTask"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# 阶段 2：TaskStatus / 状态机迁移表 / pipeline_steps 契约统一来自 domain（阶段 0 冻结）。
# str Enum（继承 str），`TaskStatus.PENDING.value == "pending"`，兼容既有 `== "pending"` 比较。
from app.domain.document.pipeline_steps import (  # noqa: E402
    PIPELINE_STEPS_ORDER,
    default_pipeline_steps,
)
from app.domain.document.task_status import (  # noqa: E402
    InvalidStatusTransition,
    TaskStatus,
    transition,
)

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(
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
    # 阶段 2：KBKind 策略（medical_default / generic），分支判断不再用 slug
    kb_kind: Mapped[str] = mapped_column(
        String(32), default="medical_default", nullable=False, server_default="medical_default"
    )
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
    # 阶段 3：md5 全局唯一 → (md5, kb_id) 复合唯一（KB 内查重；跨 KB 复制新 task）。
    # unique index 由 Alembic 0004 管理（uq_document_tasks_md5_kb_id）。
    md5: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_minio_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    meta_minio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parsed_minio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING, nullable=False, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── 状态机门面（阶段 2：双端校验，DB CHECK + 领域异常） ──

    def set_status(self, target: TaskStatus | str) -> str:
        """流水线正常迁移（走迁移表，非法抛 InvalidStatusTransition）。"""
        self.status = transition(self.status, target).value
        return self.status

    def reset(self, reason: str = "") -> str:
        """人为重开（重传/重扫/重试）——无条件回 PENDING，**非状态机迁移**。"""
        self.status = TaskStatus.PENDING.value
        return self.status
    pipeline_steps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
