"""HttpEmbeddingPort — 经 HTTP 调独立 embedding-service（bge-m3 常驻）。

实现 `domain/ports/embedding.py::EmbeddingPort`（sync 签名不变）——
与 local 模式的 `EmbeddingFactory` 对外接口完全一致，上层（index_document /
search）无需感知 remote/local。

网络 / 5xx 统一包装为 `EmbeddingServiceError`（可重试语义，供图节点 retry_policy
捕获，类比 MineruTransientError）。客户端无连接池，每次调用短连接（内网 ms 级）。
"""
from __future__ import annotations

import httpx


class EmbeddingServiceError(RuntimeError):
    """embedding-service 调用失败（网络 / 5xx / 解析错误），可重试。"""


class HttpEmbeddingPort:
    def __init__(self, base_url: str, timeout: float = 60.0):
        # timeout 放宽：批量接口整篇编码数十秒级（cpu bge-m3）
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def embed_query(self, text: str) -> list[float]:
        try:
            r = httpx.post(
                f"{self._base_url}/embed", json={"text": text}, timeout=self._timeout
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbeddingServiceError(f"embed_query 失败: {e}") from e
        return r.json()["embedding"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(
                f"{self._base_url}/embed/batch", json={"texts": texts}, timeout=self._timeout
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbeddingServiceError(f"embed_documents 失败: {e}") from e
        return r.json()["embeddings"]

    def check_health(self) -> bool:
        """start() 预热探测：服务就绪且 status=ok。"""
        try:
            r = httpx.get(f"{self._base_url}/health", timeout=5.0)
            r.raise_for_status()
            return r.json().get("status") == "ok"
        except httpx.HTTPError:
            return False

    def release(self) -> None:
        """占位：与 EmbeddingFactory.release 对齐（客户端无资源需释放）。"""
        return
