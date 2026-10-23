"""Settings 单一真相源测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.settings import Settings


def _settings(**env):
    """构造与真实 .env 隔离的 Settings（pydantic-settings 默认读 .env，单测禁用）。"""
    return Settings(_env_file=None, **env)


def test_defaults_without_env(env_ctx):
    with env_ctx(
        JWT_SECRET_KEY="x",
        POSTGRES_HOST=None, POSTGRES_PORT=None, POSTGRES_USER=None,
        POSTGRES_PASSWORD=None, POSTGRES_DB=None,
        MINERU_TOKENS=None, MINERU_API_TOKEN=None,
    ):
        s = _settings()
    assert s.postgres_host == "localhost"
    assert s.postgres_port == 5432
    assert s.resolved_database_url.startswith("postgresql+asyncpg://")
    assert s.mineru_token_list == []


def test_env_override(env_ctx):
    with env_ctx(JWT_SECRET_KEY="x", POSTGRES_HOST="db", POSTGRES_PORT="5433"):
        s = _settings()
    assert s.postgres_host == "db"
    assert s.postgres_port == 5433
    assert "db:5433" in s.resolved_database_url


def test_invalid_int_raises(env_ctx):
    with env_ctx(JWT_SECRET_KEY="x", POSTGRES_PORT="not-a-number"):
        with pytest.raises(ValidationError):
            _settings()


def test_missing_jwt_secret_raises(env_ctx):
    with env_ctx(JWT_SECRET_KEY=None):
        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            _settings()


def test_mineru_tokens_parsing(env_ctx):
    with env_ctx(JWT_SECRET_KEY="x", MINERU_TOKENS="tok_a,tok_b"):
        s = _settings()
    assert s.mineru_token_list == ["tok_a", "tok_b"]


def test_mineru_tokens_fallback_api_token(env_ctx):
    with env_ctx(JWT_SECRET_KEY="x", MINERU_TOKENS=None, MINERU_API_TOKEN="tok_c"):
        s = _settings()
    assert s.mineru_token_list == ["tok_c"]


def test_cors_parsing(env_ctx):
    with env_ctx(JWT_SECRET_KEY="x", CORS_ORIGINS="http://a, http://b"):
        s = _settings()
    assert s.cors_origins_list == ["http://a", "http://b"]


def test_cors_default_matches_vite_port(env_ctx):
    """默认 CORS 必须含前端真实端口 5171（5173 在 Windows 保留段无法绑定）。

    回归：默认值曾是 5173，而 vite 实际跑 5171。开发期走 vite 代理属同源、
    CORS 不触发，故问题长期不可见；前端独立部署时才会全站被拒。
    """
    with env_ctx(JWT_SECRET_KEY="x", CORS_ORIGINS=None):
        s = _settings()
    assert "http://localhost:5171" in s.cors_origins_list
    assert "http://localhost:5173" not in s.cors_origins_list


def test_bootstrap_admin_password_defaults_empty(env_ctx):
    """默认管理员密码默认空 —— 不得内置 admin123 这类公开默认凭据。"""
    with env_ctx(JWT_SECRET_KEY="x", BOOTSTRAP_ADMIN_PASSWORD=None):
        s = _settings()
    assert s.bootstrap_admin_password == ""
    assert s.bootstrap_admin_username == "admin"


def test_max_upload_files_independent_of_chunk_size(env_ctx):
    """批量上传文件数上限与切分粒度 chunk_size 是两个独立配置。"""
    with env_ctx(
        JWT_SECRET_KEY="x", CHUNK_SIZE="256", MAX_UPLOAD_FILES="20",
    ):
        s = _settings()
    assert s.chunk_size == 256
    assert s.max_upload_files == 20
