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
