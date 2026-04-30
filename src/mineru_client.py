"""MinerU API 客户端 — 批量上传 + 任务提交"""

import asyncio
import traceback

import httpx

from src.config import (
    MINERU_API_BASE,
    MINERU_API_TOKEN,
    MINERU_ENABLE_FORMULA,
    MINERU_ENABLE_OCR,
    MINERU_ENABLE_TABLE,
    MINERU_LANGUAGE,
    MINERU_MODEL_VERSION,
)

AUTH_HEADER = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MINERU_API_TOKEN}",
}

# API 调用用较短超时，上传/下载用较长超时
API_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=30.0)


def _api_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        proxy=None, http2=False, trust_env=False, timeout=API_TIMEOUT,
    )


def _upload_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        proxy=None, http2=False, trust_env=False, timeout=UPLOAD_TIMEOUT,
    )


async def _post(path: str, body: dict) -> dict:
    async with _api_client() as http:
        resp = await http.post(
            f"{MINERU_API_BASE}{path}", headers=AUTH_HEADER, json=body,
        )
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0:
            raise RuntimeError(f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}")
        return j["data"]


async def _get(path: str) -> dict:
    async with _api_client() as http:
        resp = await http.get(f"{MINERU_API_BASE}{path}", headers=AUTH_HEADER)
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0:
            raise RuntimeError(f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}")
        return j["data"]


async def _put_upload(upload_url: str, filename: str, data: bytes) -> None:
    """PUT 上传文件到 OSS 预签名 URL"""
    print(f"  [MinerU] 上传 {filename} ({len(data)/1024:.0f}KB)...")
    async with _upload_client() as http:
        resp = await http.put(upload_url, content=data)
        resp.raise_for_status()
    print(f"  [MinerU] {filename} 上传完成")


async def submit_batch(
    file_infos: list[dict],
) -> tuple[str, list[str]]:
    """
    批量上传文件并提交解析。file_infos: [{"name": "x.pdf", "data": b"...", "md5": "abc"}]
    返回 (batch_id, md5_list)。
    """
    # 1. 申请上传链接
    files = []
    for fi in file_infos:
        files.append({
            "name": fi["name"],
            "is_ocr": MINERU_ENABLE_OCR,
            "data_id": fi["md5"],
        })

    body = {
        "files": files,
        "model_version": MINERU_MODEL_VERSION,
        "enable_formula": MINERU_ENABLE_FORMULA,
        "enable_table": MINERU_ENABLE_TABLE,
        "language": MINERU_LANGUAGE,
    }
    print(f"  [MinerU] 申请上传 URL ({len(files)} 个文件)...")
    data = await _post("/api/v4/file-urls/batch", body)
    batch_id = data["batch_id"]
    file_urls: list[str] = data["file_urls"]
    print(f"  [MinerU] batch_id={batch_id}")

    # 2. 逐个上传，单文件失败不影响整体
    errors = []
    for idx, fi in enumerate(file_infos):
        try:
            await _put_upload(file_urls[idx], fi["name"], fi["data"])
        except Exception as e:
            err_msg = f"{fi['name']}: {e}"
            print(f"  [MinerU] 上传失败: {err_msg}")
            traceback.print_exc()
            errors.append(err_msg)

    if errors:
        raise RuntimeError(f"上传失败 ({len(errors)}/{len(file_infos)}): {'; '.join(errors)}")

    md5_list = [fi["md5"] for fi in file_infos]
    return batch_id, md5_list


async def poll_batch(batch_id: str) -> list[dict]:
    """轮询批量任务结果，返回 extract_result 列表"""
    data = await _get(f"/api/v4/extract-results/batch/{batch_id}")
    return data.get("extract_result", [])


async def download_result(download_url: str) -> bytes:
    async with _upload_client() as http:
        resp = await http.get(download_url)
        resp.raise_for_status()
        return resp.content
