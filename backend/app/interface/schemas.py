"""Pydantic schemas"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    status: str
    title: str
    summary: str | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[CitationSchema] | None = None
    rag_steps: dict | None = None
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
