"""MinIO 三桶对象存储 — 转发到 AppContainer（阶段 1）。

函数签名与旧版一致；客户端生命周期（lazy + close）由容器统一管理。
"""
from __future__ import annotations

from datetime import timedelta


def _adapter():
    from app.interface.deps import get_container
    return get_container().get_minio()


def get_minio():
    """经 AppContainer 获取 MinIO 客户端（兼容旧调用）。"""
    return _adapter().client


async def init_buckets():
    """确保四个桶存在。"""
    await _adapter().init_buckets()


def upload_raw_pdf(md5: str, filename: str, data: bytes) -> str:
    return _adapter().upload_raw_pdf(md5, filename, data)


def upload_meta_json(md5: str, filename: str, data: bytes) -> str:
    return _adapter().upload_meta_json(md5, filename, data)


def upload_parsed_assets(md5: str, zip_bytes: bytes) -> str:
    return _adapter().upload_parsed_assets(md5, zip_bytes)


def check_parsed_exists(md5: str) -> bool:
    return _adapter().check_parsed_exists(md5)


def upload_chunk_json(uuid: str, data: bytes) -> str:
    return _adapter().upload_chunk_json(uuid, data)


def chunk_json_exists(uuid: str) -> bool:
    return _adapter().chunk_json_exists(uuid)


def read_parsed_markdown(md5: str) -> str:
    return _adapter().read_parsed_markdown(md5)


def presigned_get_object(bucket: str, object_path: str, expires=timedelta(hours=1)) -> str:
    return _adapter().presigned_get_object(bucket, object_path, expires=expires)


def list_objects(bucket: str, prefix: str, recursive: bool = True):
    return _adapter().list_objects(bucket, prefix=prefix, recursive=recursive)


def get_object(bucket: str, object_path: str):
    return _adapter().get_object(bucket, object_path)
