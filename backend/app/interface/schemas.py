"""Pydantic schemas"""

import logging
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.lifecycle import StepStatus, normalize_step_status

logger = logging.getLogger(__name__)


class TaskCreateResponse(BaseModel):
    id: uuid.UUID
    md5: str
    original_name: str
    status: str
    raw_minio_path: str
    message: str


class TaskStatusResponse(BaseModel):
    id: uuid.UUID
    md5: str
    original_name: str
    status: str
    parsed_minio_path: str | None = None
    error_msg: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Auth ────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=6, max_length=50)


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    enabled: bool
    last_login: datetime | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


# ── User Management ─────────────────────────────────────────


class UserUpdateRequest(BaseModel):
    enabled: bool | None = None
    role: str | None = None


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


# ── Chat / SSE ──────────────────────────────────────────────


class ChatSendRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    kb_id: str | None = None


class CitationSchema(BaseModel):
    id: str
    title: str
    source: str
    snippet: str
    page: int | None = None
    doc_id: str | None = None
    relevance: float = 0.0


class RagStepSchema(BaseModel):
    """RAG 步骤的响应形状。

    `status` 走 `StepStatus` 枚举，但配了 **before 校验器**：历史数据里的
    `completed` / `success` / `error` 在**读取边界**归一，而不是让整个请求 500。

    为什么不直接严格拒绝：`GET /conversations/{id}/messages` 返回整个消息列表，
    只要有一条老消息带 `completed`，该会话就彻底打不开。归一 + 告警是更稳妥的取舍。
    """

    status: StepStatus
    title: str
    summary: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: object) -> object:
        out = normalize_step_status(v)
        if isinstance(v, str) and v != out:
            # 不静默：出现即说明有旧写入方或脏数据，留痕便于排查
            logger.warning("rag_steps.status 归一：%r → %r", v, out)
        return out


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[CitationSchema] | None = None
    # 收紧：每个 step 都按 RagStepSchema 校验（status 在读取边界归一）
    rag_steps: dict[str, RagStepSchema] | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime
    created_at: datetime
    message_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    title: str = "新对话"


# ── Knowledge Base ─────────────────────────────────────────

class KBCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    slug: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")


class KBResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    slug: str
    es_index: str
    milvus_collection: str
    created_at: datetime | None = None
    document_count: int = 0
    has_ready_docs: bool = False
    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_name: str
    md5: str
    status: str
    kb_id: uuid.UUID | None = None
    pipeline_steps: dict | None = None
    created_at: datetime | None = None
    error_msg: str | None = None
    model_config = ConfigDict(from_attributes=True)


# ── Document / PDF ──────────────────────────────────────────


class DocumentPdfResponse(BaseModel):
    pdf_url: str
    total_pages: int = 0
