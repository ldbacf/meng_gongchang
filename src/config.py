"""全局配置，从 .env 加载"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── PostgreSQL ──────────────────────────────────────────────
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "mineru")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "mineru123")
POSTGRES_DB = os.getenv("POSTGRES_DB", "mineru_pipeline")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

# ── Redis ──────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}")
REDIS_QUEUE = os.getenv("REDIS_QUEUE", "mineru:poll_queue")

# ── MinIO ──────────────────────────────────────────────────
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_RAW_BUCKET = os.getenv("MINIO_RAW_BUCKET", "raw-docs")
MINIO_META_BUCKET = os.getenv("MINIO_META_BUCKET", "doc-meta")
MINIO_PARSED_BUCKET = os.getenv("MINIO_PARSED_BUCKET", "parsed-data")
MINIO_CHUNKS_BUCKET = os.getenv("MINIO_CHUNKS_BUCKET", "chunks")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000")

# ── MinerU API ─────────────────────────────────────────────
MINERU_API_BASE = os.getenv("MINERU_API_BASE", "https://mineru.net").rstrip("/")
# 兼容旧版: 只用 MINERU_API_TOKEN 也可
MINERU_API_TOKEN = os.getenv("MINERU_API_TOKEN", "")
MINERU_TOKENS_RAW = (
    os.getenv("MINERU_TOKENS")
    or (MINERU_API_TOKEN if MINERU_API_TOKEN else "")
)
MINERU_MODEL_VERSION = os.getenv("MINERU_MODEL_VERSION", "vlm")
MINERU_ENABLE_OCR = os.getenv("MINERU_ENABLE_OCR", "false").lower() == "true"
MINERU_ENABLE_FORMULA = os.getenv("MINERU_ENABLE_FORMULA", "true").lower() == "true"
MINERU_ENABLE_TABLE = os.getenv("MINERU_ENABLE_TABLE", "true").lower() == "true"
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "ch")
MINERU_MAX_PAGES_PER_KEY = int(os.getenv("MINERU_MAX_PAGES_PER_KEY", "1000"))
MINERU_BATCH_SIZE = int(os.getenv("MINERU_BATCH_SIZE", "10"))

# ── Elasticsearch ─────────────────────────────────────────
ES_HOST = os.getenv("ES_HOST", "localhost")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_USER = os.getenv("ES_USER", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")
ES_INDEX = os.getenv("ES_INDEX", "chunks")

# ── Milvus ────────────────────────────────────────────────
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "chunks")

# ── 硅基流动 Rerank ──────────────────────────────────────
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_RERANK_MODEL = os.getenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")

# ── DeepSeek 意图识别 & LLM 回答 ──────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_INTENT_MODEL = os.getenv("DEEPSEEK_INTENT_MODEL", "deepseek-v4-flash")
DEEPSEEK_ANSWER_MODEL = os.getenv("DEEPSEEK_ANSWER_MODEL", "deepseek-v4-pro")

# ── Worker ─────────────────────────────────────────────────
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
MAX_POLL_TIME = int(os.getenv("MAX_POLL_TIME", "1200"))
CHUNK_SIZE = 50
