"""MinIO 客户端适配器 — 三桶对象存储（raw-docs / doc-meta / parsed-data / chunks）。

原 `src/minio_client.py` 的函数全部迁入本适配器（签名不变），
生命周期（lazy client + close）由 AppContainer 管理。
"""
from __future__ import annotations

import re
from io import BytesIO

from minio import Minio

from app.infrastructure.settings import Settings, get_settings


class MinioAdapter:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client: Minio | None = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            s = self._settings
            self._client = Minio(
                s.minio_endpoint,
                access_key=s.minio_access_key,
                secret_key=s.minio_secret_key,
                secure=s.minio_secure,
            )
        return self._client

    # ── 生命周期 ──────────────────────────────────────────────

    async def init_buckets(self) -> None:
        """确保四个桶存在（与 CLAUDE.md 红线一致：只建桶，不动数据）。"""
        s = self._settings
        for bucket in (
            s.minio_raw_bucket, s.minio_meta_bucket,
            s.minio_parsed_bucket, s.minio_chunks_bucket,
        ):
            found = self.client.bucket_exists(bucket)
            if not found:
                self.client.make_bucket(bucket)
                print(f"[MinIO] 创建桶: {bucket}")
            else:
                print(f"[MinIO] 桶已存在: {bucket}")

    def close(self) -> None:
        self._client = None  # MinIO SDK 无显式 close；释放引用即可

    # ── 上传/下载 ─────────────────────────────────────────────

    def upload_raw_pdf(self, md5: str, filename: str, data: bytes) -> str:
        """上传原始 PDF 到 raw-docs/{md5}/"""
        path = f"{md5}/{filename}"
        self.client.put_object(
            self._settings.minio_raw_bucket, path, BytesIO(data), length=len(data),
            content_type="application/pdf",
        )
        return path

    def upload_meta_json(self, md5: str, filename: str, data: bytes) -> str:
        """上传元信息 JSON 到 doc-meta/{md5}/{filename}"""
        path = f"{md5}/{filename}"
        self.client.put_object(
            self._settings.minio_meta_bucket, path, BytesIO(data), length=len(data),
            content_type="application/json",
        )
        return path

    def upload_parsed_assets(self, md5: str, zip_bytes: bytes) -> str:
        """
        上传解析产物到 parsed-data/{md5}/。
        对 full.md 做图片路径替换后将所有资产写入 MinIO。
        返回 full.md 的 MinIO URL。
        """
        import zipfile

        s = self._settings
        prefix = f"{md5}/"
        images_dir = f"{md5}/images/"
        full_md_content = None

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for member in zf.namelist():
                member_name = member.rstrip("/")
                if member_name.endswith("/") or not member_name:
                    continue

                file_bytes = zf.read(member)
                base_name = member_name.rsplit("/", 1)[-1] if "/" in member_name else member_name

                if base_name == "full.md" or member_name.endswith("/full.md"):
                    full_md_content = file_bytes
                elif base_name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
                    img_path = f"{images_dir}{base_name}"
                    ct = _content_type(base_name)
                    self.client.put_object(
                        s.minio_parsed_bucket, img_path, BytesIO(file_bytes),
                        length=len(file_bytes), content_type=ct,
                    )
                else:
                    obj_path = f"{prefix}{base_name}"
                    self.client.put_object(
                        s.minio_parsed_bucket, obj_path, BytesIO(file_bytes),
                        length=len(file_bytes),
                    )

        if full_md_content:
            md_text = full_md_content.decode("utf-8", errors="replace")
            public_prefix = f"{s.minio_public_url}/{s.minio_parsed_bucket}/{md5}"
            md_text = re.sub(
                r"!\[([^\]]*)\]\(images/([^)]+)\)",
                rf"![\1]({public_prefix}/images/\2)",
                md_text,
            )
            md_path = f"{prefix}full.md"
            md_bytes = md_text.encode("utf-8")
            self.client.put_object(
                s.minio_parsed_bucket, md_path, BytesIO(md_bytes),
                length=len(md_bytes), content_type="text/markdown",
            )

        return f"{s.minio_public_url}/{s.minio_parsed_bucket}/{prefix}full.md"

    def check_parsed_exists(self, md5: str) -> bool:
        """验证 parsed-data/{md5}/ 下是否存在核心产物 full.md"""
        try:
            self.client.stat_object(self._settings.minio_parsed_bucket, f"{md5}/full.md")
            return True
        except Exception:
            return False

    def upload_chunk_json(self, uuid: str, data: bytes) -> str:
        """上传切分结果 JSON 到 chunks/{uuid}.json（桶不存在则自动创建）"""
        self._ensure_bucket(self._settings.minio_chunks_bucket)
        path = f"{uuid}.json"
        self.client.put_object(
            self._settings.minio_chunks_bucket, path, BytesIO(data), length=len(data),
            content_type="application/json",
        )
        return path

    def chunk_json_exists(self, uuid: str) -> bool:
        """检查 chunks/{uuid}.json 是否已存在"""
        try:
            self.client.stat_object(self._settings.minio_chunks_bucket, f"{uuid}.json")
            return True
        except Exception:
            return False

    def read_parsed_markdown(self, md5: str) -> str:
        """从 MinIO parsed-data/{md5}/ 读取 full.md"""
        obj = self.client.get_object(self._settings.minio_parsed_bucket, f"{md5}/full.md")
        return obj.read().decode("utf-8")

    def presigned_get_object(self, bucket: str, object_path: str, expires) -> str:
        return self.client.presigned_get_object(bucket, object_path, expires=expires)

    def list_objects(self, bucket: str, prefix: str, recursive: bool = True):
        return self.client.list_objects(bucket, prefix=prefix, recursive=recursive)

    def get_object(self, bucket: str, object_path: str):
        return self.client.get_object(bucket, object_path)

    # ── 内部 ──────────────────────────────────────────────────

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)


def _content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "webp": "image/webp",
        "gif": "image/gif", "bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
