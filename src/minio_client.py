"""MinIO 三桶对象存储 — raw-docs / doc-meta / parsed-data"""

import re
from io import BytesIO

from minio import Minio

from src.config import (
    MINIO_ACCESS_KEY,
    MINIO_CHUNKS_BUCKET,
    MINIO_ENDPOINT,
    MINIO_META_BUCKET,
    MINIO_PARSED_BUCKET,
    MINIO_PUBLIC_URL,
    MINIO_RAW_BUCKET,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    return _client


async def init_buckets():
    """确保三桶存在"""
    client = get_minio()
    for bucket in (MINIO_RAW_BUCKET, MINIO_META_BUCKET, MINIO_PARSED_BUCKET, MINIO_CHUNKS_BUCKET):
        found = client.bucket_exists(bucket)
        if not found:
            client.make_bucket(bucket)
            print(f"[MinIO] 创建桶: {bucket}")
        else:
            print(f"[MinIO] 桶已存在: {bucket}")


def upload_raw_pdf(md5: str, filename: str, data: bytes) -> str:
    """上传原始 PDF 到 raw-docs/{md5}/"""
    client = get_minio()
    path = f"{md5}/{filename}"
    client.put_object(
        MINIO_RAW_BUCKET, path, BytesIO(data), length=len(data),
        content_type="application/pdf",
    )
    return path


def upload_meta_json(md5: str, filename: str, data: bytes) -> str:
    """上传元信息 JSON 到 doc-meta/{md5}/{filename}"""
    client = get_minio()
    path = f"{md5}/{filename}"
    client.put_object(
        MINIO_META_BUCKET, path, BytesIO(data), length=len(data),
        content_type="application/json",
    )
    return path


def upload_parsed_assets(md5: str, zip_bytes: bytes) -> str:
    """
    上传解析产物到 parsed-data/{md5}/。
    对 full.md 做图片路径替换后将所有资产写入 MinIO。
    返回 full.md 的 MinIO URL。
    """
    import zipfile

    client = get_minio()
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
                client.put_object(
                    MINIO_PARSED_BUCKET, img_path, BytesIO(file_bytes),
                    length=len(file_bytes), content_type=ct,
                )
            else:
                obj_path = f"{prefix}{base_name}"
                client.put_object(
                    MINIO_PARSED_BUCKET, obj_path, BytesIO(file_bytes),
                    length=len(file_bytes),
                )

    if full_md_content:
        md_text = full_md_content.decode("utf-8", errors="replace")
        public_prefix = f"{MINIO_PUBLIC_URL}/{MINIO_PARSED_BUCKET}/{md5}"
        md_text = re.sub(
            r"!\[([^\]]*)\]\(images/([^)]+)\)",
            rf"![\1]({public_prefix}/images/\2)",
            md_text,
        )
        md_path = f"{prefix}full.md"
        md_bytes = md_text.encode("utf-8")
        client.put_object(
            MINIO_PARSED_BUCKET, md_path, BytesIO(md_bytes),
            length=len(md_bytes), content_type="text/markdown",
        )

    return f"{MINIO_PUBLIC_URL}/{MINIO_PARSED_BUCKET}/{prefix}full.md"


def _content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "webp": "image/webp",
        "gif": "image/gif", "bmp": "image/bmp",
    }.get(ext, "application/octet-stream")


def check_parsed_exists(md5: str) -> bool:
    """验证 parsed-data/{md5}/ 下是否存在核心产物 full.md"""
    client = get_minio()
    try:
        client.stat_object(MINIO_PARSED_BUCKET, f"{md5}/full.md")
        return True
    except Exception:
        return False


def upload_chunk_json(uuid: str, data: bytes) -> str:
    """上传切分结果 JSON 到 chunks/{uuid}.json（桶不存在则自动创建）"""
    client = get_minio()
    _ensure_bucket(MINIO_CHUNKS_BUCKET)
    path = f"{uuid}.json"
    client.put_object(
        MINIO_CHUNKS_BUCKET, path, BytesIO(data), length=len(data),
        content_type="application/json",
    )
    return path


def _ensure_bucket(bucket: str):
    """同步检查并创建桶"""
    client = get_minio()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def chunk_json_exists(uuid: str) -> bool:
    """检查 chunks/{uuid}.json 是否已存在"""
    client = get_minio()
    try:
        client.stat_object(MINIO_CHUNKS_BUCKET, f"{uuid}.json")
        return True
    except Exception:
        return False
