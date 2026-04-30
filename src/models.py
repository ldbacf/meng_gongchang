"""PostgreSQL 业务账本 — DocumentTask"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    FAILED = "failed"


class DocumentTask(Base):
    __tablename__ = "document_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    md5: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_minio_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    parsed_minio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING, nullable=False, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
