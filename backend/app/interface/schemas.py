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
    #: 「重新生成」时传被替换的那条 AI 消息 id。
    #: 带上它表示：复用 `message`（原提问）重新回答，**不新建用户消息**，
    #: 并在新回答落库的同一事务里删掉这条旧回答。
    regenerate_message_id: str | None = None


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


class CitationBox(BaseModel):
    """一处原文定位。

    **坐标来自 MinerU 的 `content_list.json`，不是文本搜索**：
    每个条目带 `bbox`（0-1000 归一化）与 `page_idx`（0-based）。
    前端按 bbox 在 PDF 页面图层上画高亮框，不依赖文本层内容是否一致 ——
    这解决了原实现「pdf.js find 搜纯文本、标点不一致就 0 命中」的顽疾。
    """

    page: int = Field(description="页码，1-based（后端已 +1，前端直接用）")
    bbox: list[float] = Field(description="[x0, y0, x1, y1]，相对页面宽高的 0-1000 归一化值")
    text: str = Field(default="", description="该条目的原始文本，用于前端校验与展示")


class CitationLocateResponse(BaseModel):
    found: bool
    boxes: list[CitationBox] = []
    total_pages: int = 0
    md5: str | None = None
    message: str = ""


# ── 证据卡 ────────────────────────────────────────────────────
#
# 与 /locate 的分工：
#   /locate   回答「这句话在 PDF 第几页哪个位置」→ 给 pdf.js 画框
#   /evidence 回答「这篇文献说了什么、方法是什么、上下文是什么」→ 给证据卡渲染
#
# 两者都从 parsed-data + ES 取数，但用途完全不同，不要合并：
# 证据卡要的是**可读文本**（清洗过的），定位要的是**坐标**。


class AbstractSectionSchema(BaseModel):
    """结构式摘要的一段。`key` 为空表示整段没有分段键。"""

    key: str = Field(description="背景/目的/方法/结果/结论；空字符串表示无分段")
    text: str


class SampleSizeSchema(BaseModel):
    """抽到的样本量。**启发式结果，不是事实**，前端应标为提示。"""

    value: int
    unit: str = Field(description="例/名/人 = 受试者数；篇/项 = 纳入文献数")
    is_subject_count: bool = Field(
        description="false 时前端不能标成「样本量」，应显示「纳入 N 篇」"
    )


class EvidencePassage(BaseModel):
    """连续正文：上文 + 命中 + 下文。

    **刻意不拆成三个独立字段给前端拼接**：读者要读的是一段连续的话，
    原文只是被 chunk 边界切开了。前端按 顺序渲染 passage，命中块的段落
    单独用 `hit` 标出，其余用褪色样式，这样视觉上是连续文本而不是三个方块。
    """

    prev_heading: str = ""
    prev_text: str = Field(default="", description="上文尾段（尽量从句末开始）")
    hit_heading: str = ""
    hit_paragraphs: list[str] = Field(default_factory=list, description="命中块，已清洗分段")
    next_heading: str = ""
    next_text: str = Field(default="", description="下文首段（尽量在句末结束）")
    has_prev: bool = False
    has_next: bool = False


class EvidenceResponse(BaseModel):
    """一篇文献的证据卡数据。

    `abstract_sections` 为空 表示该文没有结构式摘要（全库 337/1248），
    前端应回退到 `abstract_raw` 整段展示，**不要伪造结论段**。
    """

    doc_id: str
    title: str = ""
    authors: str = ""
    journal: str = ""
    source: str = ""
    year: str = ""
    article_type: str = ""
    doi: str = ""
    keywords: list[str] = Field(default_factory=list)

    abstract_raw: str = ""
    abstract_sections: list[AbstractSectionSchema] = Field(default_factory=list)
    has_conclusion: bool = False
    sample_size: SampleSizeSchema | None = None

    passage: EvidencePassage | None = None
    md5: str | None = None
    message: str = ""
