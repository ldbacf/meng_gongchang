"""对象存储端口抽象 — MinioAdapter 实现之。"""
from __future__ import annotations

from typing import Protocol


class StoragePort(Protocol):
    """MinIO 三桶对象存储端口。"""

    def upload_raw_pdf(self, md5: str, filename: str, data: bytes) -> str: ...

    def upload_parsed_assets(self, md5: str, zip_bytes: bytes) -> str: ...

    def read_parsed_markdown(self, md5: str) -> str: ...

    def check_parsed_exists(self, md5: str) -> bool: ...

    def upload_chunk_json(self, uuid: str, data: bytes) -> str: ...
