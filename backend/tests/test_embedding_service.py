"""E-1~E-5 — Embedding 独立服务（bge-m3 常驻）。

全部离线（不加载模型 / 不连 PG）：
- E-1 HttpEmbeddingPort 客户端（mock httpx，验证请求构造与响应解析 + 错误包装）。
- E-2 /health 端点返回 {status, dim}。
- E-3 /embed 单条 + /embed/batch 批量（mock 模型，验证 1024 维归一化）。
- E-4 双模式切换：remote → HttpEmbeddingPort，local → EmbeddingFactory。
- E-5 两种模式对外接口一致（都走 embed_query / embed_documents）。
"""
from __future__ import annotations

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.application import embedding_server
from app.application.embedding_server import app
from app.infrastructure.adapters.embedding import EmbeddingFactory
from app.infrastructure.adapters.embedding_http import (
    EmbeddingServiceError,
    HttpEmbeddingPort,
)
from app.infrastructure.container import AppContainer
from app.infrastructure.settings import Settings


# ── E-1 ─────────────────────────────────────────────────────────


def test_embedding_http_client_builds_requests(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_post(url, json=None, timeout=None):
        calls.append((url, json, timeout))
        if url.endswith("/embed/batch"):
            return _Resp({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
        return _Resp({"embedding": [0.1, 0.2]})

    monkeypatch.setattr("httpx.post", _fake_post)
    port = HttpEmbeddingPort("http://localhost:8084")

    assert port.embed_query("儿童用药") == [0.1, 0.2]
    assert port.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]

    assert calls[0][0] == "http://localhost:8084/embed"
    assert calls[0][1] == {"text": "儿童用药"}
    assert calls[1][0] == "http://localhost:8084/embed/batch"
    assert calls[1][1] == {"texts": ["a", "b"]}
    # 超时已放宽（批量数十秒级）
    assert calls[0][2] == calls[1][2] and calls[0][2] == 60.0


def test_embedding_http_client_wraps_errors(monkeypatch):
    def _fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused", request=None)

    monkeypatch.setattr("httpx.post", _fake_post)
    port = HttpEmbeddingPort("http://localhost:8084")

    with pytest.raises(EmbeddingServiceError):
        port.embed_query("x")
    with pytest.raises(EmbeddingServiceError):
        port.embed_documents(["x"])


# ── E-2 / E-3 ────────────────────────────────────────────────────


class _FakeModel:
    """mock bge-m3：encode 返回 L2 归一化、1024 维 ndarray。"""

    def encode(self, texts, normalize_embeddings=True):
        if isinstance(texts, str):
            texts = [texts]
        arr = np.random.randn(len(texts), 1024).astype(np.float32)
        if normalize_embeddings:
            arr = arr / np.linalg.norm(arr, axis=1, keepdims=True)
        return arr


@pytest.fixture
def server_env(monkeypatch):
    """隔离 Settings（禁读 .env）+ mock 模型（不加载 4.3G bge-m3）。"""
    s = Settings(_env_file=None, jwt_secret_key="x", embedding_dim=1024)
    monkeypatch.setattr(embedding_server, "get_settings", lambda: s)
    monkeypatch.setattr(embedding_server, "_get_model", lambda: _FakeModel())
    return s


def test_embedding_server_health(server_env):
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "dim": 1024}


def test_embedding_server_embed_single(server_env):
    r = TestClient(app).post("/embed", json={"text": "儿童用药政策"})
    assert r.status_code == 200
    vec = r.json()["embedding"]
    assert len(vec) == 1024
    assert all(isinstance(x, float) for x in vec)
    # L2 归一化：模长 ≈ 1
    assert abs(np.linalg.norm(np.array(vec)) - 1.0) < 1e-4


def test_embedding_server_embed_batch(server_env):
    r = TestClient(app).post("/embed/batch", json={"texts": ["a", "b", "c"]})
    assert r.status_code == 200
    vecs = r.json()["embeddings"]
    assert len(vecs) == 3
    assert all(len(v) == 1024 for v in vecs)
    for v in vecs:
        assert abs(np.linalg.norm(np.array(v)) - 1.0) < 1e-4


# ── E-4 ──────────────────────────────────────────────────────────


def test_embedding_mode_remote_returns_http_port():
    s = Settings(
        _env_file=None, jwt_secret_key="x",
        embedding_mode="remote", embedding_service_url="http://embed:8084",
    )
    assert isinstance(AppContainer(settings=s).get_embedder(), HttpEmbeddingPort)


def test_embedding_mode_local_returns_factory():
    s = Settings(_env_file=None, jwt_secret_key="x", embedding_mode="local")
    assert isinstance(AppContainer(settings=s).get_embedder(), EmbeddingFactory)


# ── E-5 ──────────────────────────────────────────────────────────


def test_embedding_port_implementations_conform(monkeypatch):
    """两种模式的 embedder 都实现 embed_query/embed_documents，调用点签名一致。"""
    factory = EmbeddingFactory()

    class _M:
        def embed_documents(self, texts):
            return [[1.0 * len(texts)] * 2 for _ in texts]

        def embed_query(self, text):
            return [2.0 * len(text)] * 2

    monkeypatch.setattr(factory, "get_hf_embeddings", lambda: _M())

    assert factory.embed_query("hic") == [6.0, 6.0]
    assert factory.embed_documents(["a", "b"]) == [[2.0, 2.0], [2.0, 2.0]]

    # remote：结构上暴露同样两个方法（网络细节在 E-1 覆盖）
    port = HttpEmbeddingPort("http://x")
    assert callable(port.embed_query)
    assert callable(port.embed_documents)
