"""Elasticsearch 客户端适配器 — 生命周期由 AppContainer 管理。

- lazy 创建（首次访问才建连接），带 request_timeout / auth / 重连。
- `close()` 释放连接，容器 shutdown 时调用。
- 供 `src/search.get_es_client()` 等经容器取用，禁止模块级单例。
"""
from __future__ import annotations

from elasticsearch import Elasticsearch

from app.infrastructure.settings import Settings, get_settings


class ElasticsearchAdapter:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client: Elasticsearch | None = None

    @property
    def client(self) -> Elasticsearch:
        if self._client is None:
            s = self._settings
            kwargs = {
                "request_timeout": 30,
                "retry_on_timeout": True,
                "max_retries": 3,
            }
            if s.es_user and s.es_password:
                self._client = Elasticsearch(
                    f"http://{s.es_user}:{s.es_password}@{s.es_host}:{s.es_port}",
                    **kwargs,
                )
            else:
                self._client = Elasticsearch(
                    f"http://{s.es_host}:{s.es_port}", **kwargs,
                )
        return self._client

    def ping(self) -> bool:
        """健康检查 — 供容器 start()/健康探针使用。"""
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
