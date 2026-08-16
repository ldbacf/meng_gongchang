"""pydantic-settings 单一真相源 — 覆盖全部环境配置。

替代 `src/config.py` 与 `src/key_manager.py` 中各自 `os.getenv` 的双真相源。
- 类型校验：`POSTGRES_PORT=abc` 这类非法值在启动即抛 `ValidationError`。
- 单一来源：业务代码一律经 `get_settings()` 读取。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全部配置。字段名 ↔ 环境变量（大小写不敏感）自动映射。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ──────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "mineru"
    postgres_password: str = "mineru123"
    postgres_db: str = "mineru_pipeline"
    database_url: str | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── JWT Auth ────────────────────────────────────────────────
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    @model_validator(mode="after")
    def _require_jwt_secret(self) -> "Settings":
        if not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY 未设置！请在 .env 中配置 JWT_SECRET_KEY")
        return self

    # ── Redis ───────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_url: str | None = None
    redis_queue: str = "mineru:poll_queue"
    redis_queue_group: str = "mineru:poll_queue:group"
    redis_queue_dlq: str = "mineru:poll_queue:dlq"

    @property
    def resolved_redis_url(self) -> str:
        return self.redis_url or f"redis://{self.redis_host}:{self.redis_port}"

    # ── 可靠队列（Redis Streams）───────────────────────────────
    # 可见性超时必须大于单批最坏处理时长（MAX_POLL_TIME 1200s + 下载/索引余量），
    # 否则另一 worker 会误回收仍在正常处理的批。代价：kill-worker 恢复也要等这么久。
    queue_visibility_timeout: int = 1800
    # 超过该投递次数进 DLQ
    queue_max_delivery: int = 3

    # ── MinIO ───────────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_secure: bool = False
    minio_raw_bucket: str = "raw-docs"
    minio_meta_bucket: str = "doc-meta"
    minio_parsed_bucket: str = "parsed-data"
    minio_chunks_bucket: str = "chunks"
    minio_public_url: str = "http://localhost:9000"

    # ── MinerU API ──────────────────────────────────────────────
    mineru_api_base: str = "https://mineru.net"
    mineru_api_token: str = ""
    # 兼容旧配置：MINERU_TOKENS（多 key 逗号分隔）
    mineru_tokens: str | None = Field(default=None, validation_alias="MINERU_TOKENS")
    mineru_model_version: str = "vlm"
    mineru_enable_ocr: bool = False
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    mineru_language: str = "ch"
    mineru_max_pages_per_key: int = 1000
    mineru_batch_size: int = 10

    @property
    def mineru_token_list(self) -> list[str]:
        raw = self.mineru_tokens or self.mineru_api_token
        if not raw:
            return []
        if "," in raw:
            return [t.strip() for t in raw.split(",") if t.strip()]
        return [raw]

    # ── Elasticsearch ───────────────────────────────────────────
    es_host: str = "localhost"
    es_port: int = 9200
    es_user: str = ""
    es_password: str = ""
    es_index: str = "chunks"

    # ── Milvus ──────────────────────────────────────────────────
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "chunks"
    # 向量维度 / 索引参数（与 scripts/init_milvus.py 共用唯一来源）
    embedding_dim: int = 1024
    milvus_nlist: int = 128

    # ── SiliconFlow Rerank ──────────────────────────────────────
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_rerank_model: str = "Qwen/Qwen3-Reranker-4B"

    # ── DeepSeek ────────────────────────────────────────────────
    deepseek_api_key: str = ""
    deepseek_intent_model: str = "deepseek-v4-flash"
    deepseek_answer_model: str = "deepseek-v4-flash"

    # ── 查询扩展 ────────────────────────────────────────────────
    use_query_expansion: bool = False

    # ── CORS ────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── Worker ──────────────────────────────────────────────────
    poll_interval: int = 5
    max_poll_time: int = 1200
    chunk_size: int = 50


@lru_cache
def get_settings() -> Settings:
    """进程内缓存的 Settings 单例（环境变量不可变，lru_cache 安全）。"""
    return Settings()
