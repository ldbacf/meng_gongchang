"""全局配置 — 单一真相源转发层。

所有值统一来自 `app.infrastructure.settings.Settings`（pydantic-settings，带类型校验），
本模块仅保留旧导出名以兼容现有 import，不再直接 `os.getenv` 解析。
"""
from app.infrastructure.settings import get_settings

_s = get_settings()

# ── PostgreSQL ──────────────────────────────────────────────
POSTGRES_HOST = _s.postgres_host
POSTGRES_PORT = _s.postgres_port
POSTGRES_USER = _s.postgres_user
POSTGRES_PASSWORD = _s.postgres_password
POSTGRES_DB = _s.postgres_db
DATABASE_URL = _s.resolved_database_url

# ── JWT Auth ─────────────────────────────────────────────────
JWT_SECRET_KEY = _s.jwt_secret_key
JWT_ALGORITHM = _s.jwt_algorithm
JWT_ACCESS_EXPIRE_MINUTES = _s.jwt_access_expire_minutes
JWT_REFRESH_EXPIRE_DAYS = _s.jwt_refresh_expire_days

# ── Redis ──────────────────────────────────────────────────
REDIS_HOST = _s.redis_host
REDIS_PORT = _s.redis_port
REDIS_URL = _s.resolved_redis_url
REDIS_QUEUE = _s.redis_queue

# ── MinIO ──────────────────────────────────────────────────
MINIO_ENDPOINT = _s.minio_endpoint
MINIO_ACCESS_KEY = _s.minio_access_key
MINIO_SECRET_KEY = _s.minio_secret_key
MINIO_SECURE = _s.minio_secure
MINIO_RAW_BUCKET = _s.minio_raw_bucket
MINIO_META_BUCKET = _s.minio_meta_bucket
MINIO_PARSED_BUCKET = _s.minio_parsed_bucket
MINIO_CHUNKS_BUCKET = _s.minio_chunks_bucket
MINIO_PUBLIC_URL = _s.minio_public_url

# ── MinerU API ─────────────────────────────────────────────
MINERU_API_BASE = _s.mineru_api_base.rstrip("/")
# 兼容旧版: 只用 MINERU_API_TOKEN 也可
MINERU_API_TOKEN = _s.mineru_api_token
MINERU_TOKENS_RAW = _s.mineru_tokens or _s.mineru_api_token
MINERU_TOKEN_LIST = _s.mineru_token_list
MINERU_MODEL_VERSION = _s.mineru_model_version
MINERU_ENABLE_OCR = _s.mineru_enable_ocr
MINERU_ENABLE_FORMULA = _s.mineru_enable_formula
MINERU_ENABLE_TABLE = _s.mineru_enable_table
MINERU_LANGUAGE = _s.mineru_language
MINERU_MAX_PAGES_PER_KEY = _s.mineru_max_pages_per_key
MINERU_BATCH_SIZE = _s.mineru_batch_size

# ── Elasticsearch ─────────────────────────────────────────
ES_HOST = _s.es_host
ES_PORT = _s.es_port
ES_USER = _s.es_user
ES_PASSWORD = _s.es_password
ES_INDEX = _s.es_index

# ── Milvus ────────────────────────────────────────────────
MILVUS_HOST = _s.milvus_host
MILVUS_PORT = _s.milvus_port
MILVUS_COLLECTION = _s.milvus_collection

# ── 硅基流动 Rerank ──────────────────────────────────────
SILICONFLOW_API_KEY = _s.siliconflow_api_key
SILICONFLOW_BASE_URL = _s.siliconflow_base_url
SILICONFLOW_RERANK_MODEL = _s.siliconflow_rerank_model

# ── DeepSeek 意图识别 & LLM 回答 ──────────────────────────
DEEPSEEK_API_KEY = _s.deepseek_api_key
DEEPSEEK_INTENT_MODEL = _s.deepseek_intent_model
DEEPSEEK_ANSWER_MODEL = _s.deepseek_answer_model

# ── 查询扩展 ────────────────────────────────────────────────
USE_QUERY_EXPANSION = _s.use_query_expansion

# ── CORS ───────────────────────────────────────────────────
CORS_ORIGINS = _s.cors_origins
CORS_ORIGINS_LIST = _s.cors_origins_list

# ── Worker ─────────────────────────────────────────────────
POLL_INTERVAL = _s.poll_interval
MAX_POLL_TIME = _s.max_poll_time
CHUNK_SIZE = _s.chunk_size
