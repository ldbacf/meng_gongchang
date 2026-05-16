"""MinerU API 客户端 — 支持多 Token 额度分配"""

import asyncio
import logging
import traceback

import httpx

from src.config import (
    MINERU_API_BASE,
    MINERU_ENABLE_FORMULA,
    MINERU_ENABLE_OCR,
    MINERU_ENABLE_TABLE,
    MINERU_LANGUAGE,
    MINERU_MODEL_VERSION,
)

logger = logging.getLogger("mineru")

API_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

MAX_RETRIES = 3


def _api_client():
    return httpx.AsyncClient(
        proxy=None, http2=False, trust_env=False, timeout=API_TIMEOUT,
    )


def _upload_client():
    return httpx.AsyncClient(
        proxy=None, http2=False, trust_env=False, timeout=UPLOAD_TIMEOUT,
    )


def _auth_header(token: str) -> dict:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


async def _post(path: str, body: dict, token: str) -> dict:
    """POST 请求，429 时指数退避重试 (2s -> 4s -> 8s)"""
    for attempt in range(1, MAX_RETRIES + 1):
        async with _api_client() as http:
            resp = await http.post(
                f"{MINERU_API_BASE}{path}",
                headers=_auth_header(token), json=body,
            )
            if resp.status_code == 429 and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("429 Too Many Requests, 第%s次重试, 等待%ss", attempt, wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            j = resp.json()
            if j.get("code") != 0:
                raise RuntimeError(f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}")
            return j["data"]
    # 不会走到这里，但满足类型检查
    raise RuntimeError("429 重试耗尽")


async def _get(path: str, token: str) -> dict:
    async with _api_client() as http:
        resp = await http.get(
            f"{MINERU_API_BASE}{path}",
            headers=_auth_header(token),
        )
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0:
            raise RuntimeError(f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}")
        return j["data"]


async def _put_upload(upload_url: str, filename: str, data: bytes) -> None:
    print(f"  [MinerU] 上传 {filename} ({len(data)/1024:.0f}KB)...")
    async with _upload_client() as http:
        resp = await http.put(upload_url, content=data)
        resp.raise_for_status()
    print(f"  [MinerU] {filename} 上传完成")


async def submit_batch(
    file_infos: list[dict],
    token: str,
) -> tuple[str, list[str]]:
    """使用指定 token 批量上传并提交解析。返回 (batch_id, md5_list)。"""
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
    print(f"  [MinerU] 申请上传 URL ({len(files)} 个文件, key={token[:8]}...)...")
    data = await _post("/api/v4/file-urls/batch", body, token=token)
    batch_id = data["batch_id"]
    file_urls: list[str] = data["file_urls"]
    print(f"  [MinerU] batch_id={batch_id}")

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

    return batch_id, [fi["md5"] for fi in file_infos]


async def poll_batch(batch_id: str, token: str) -> list[dict]:
    """使用指定 token 轮询批量任务结果"""
    data = await _get(f"/api/v4/extract-results/batch/{batch_id}", token=token)
    return data.get("extract_result", [])


async def download_result(download_url: str) -> bytes:
    async with _upload_client() as http:
        resp = await http.get(download_url)
        resp.raise_for_status()
        return resp.content
