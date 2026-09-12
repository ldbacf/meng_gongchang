# MedRAG backend 镜像 — API（src.main:app）与 ingestion worker（app.application.worker）共用。
# 模型权重（models/bge-m3 ≈4.3G）不打进镜像，经 compose 卷挂载 /app/models（见 docker-compose.yml）。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv（与本地一致的工具链）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依赖层（先复制锁文件，最大化缓存命中）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 源码（app / src / cli + Alembic 迁移 + 运行期配置）
COPY app ./app
COPY src ./src
COPY cli ./cli
COPY alembic ./alembic
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# 健康检查（与 compose healthcheck 一致；worker 服务会覆盖为队列活性探针）
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
