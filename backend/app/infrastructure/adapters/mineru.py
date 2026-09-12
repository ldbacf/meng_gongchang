"""MinerU API 客户端适配器 — 多 Token 提交 / 轮询 / 下载。

结构化异常（替代 worker 字符串匹配，阶段 1 引入异常类型、阶段 3 正式落地分类）：
- `MineruFatalError`：不可恢复（batch 不存在 / 无权限 / token 失效 / 上传失败）。
- `MineruTransientError`：可重试（网络错误 / 429 重试耗尽 / 5xx）。
"""
from __future__ import annotations

import asyncio
import logging
import traceback

import httpx

from app.infrastructure.settings import Settings, get_settings

logger = logging.getLogger("mineru")

API_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

MAX_RETRIES = 3

# 致命错误文案（与旧 worker 字符串匹配对齐，分类迁移在阶段 3 正式落地）
_FATAL_KEYWORDS = ("找不到任务", "没有权限", "Token 错误", "Token 过期")


class MineruFatalError(RuntimeError):
    """MinerU 不可恢复错误 — 直接标记失败，不重试。"""


class MineruTransientError(RuntimeError):
    """MinerU 可重试错误 — 429/网络/5xx。"""


def _classify(exc: Exception) -> Exception:
    """把 httpx/RuntimeError 归类为结构化异常（原样返回已结构化的）。"""
    if isinstance(exc, (MineruFatalError, MineruTransientError)):
        return exc
    msg = str(exc)
    if any(kw in msg for kw in _FATAL_KEYWORDS):
        return MineruFatalError(msg)
    return MineruTransientError(msg)


class MineruClient:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    @property
    def s(self) -> Settings:
        return self._settings

    # ── 内部请求 ──────────────────────────────────────────────

    async def _post(self, path: str, body: dict, token: str) -> dict:
        """POST 请求，429 时指数退避重试 (2s -> 4s -> 8s)。"""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self._api_client() as http:
                    resp = await http.post(
                        f"{self.s.mineru_api_base}{path}",
                        headers=_auth_header(token), json=body,
                    )
            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise MineruTransientError(f"MinerU 网络错误: {e}") from e

            if resp.status_code == 429 and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("429 Too Many Requests, 第%s次重试, 等待%ss", attempt, wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise MineruTransientError(f"MinerU HTTP {resp.status_code}: {e}") from e
            j = resp.json()
            if j.get("code") != 0:
                err = f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}"
                raise _classify(RuntimeError(err))
            return j["data"]
        raise MineruTransientError("MinerU 429 重试耗尽")

    async def _get(self, path: str, token: str) -> dict:
        try:
            async with self._api_client() as http:
                resp = await http.get(
                    f"{self.s.mineru_api_base}{path}",
                    headers=_auth_header(token),
                )
        except httpx.HTTPError as e:
            raise MineruTransientError(f"MinerU 网络错误: {e}") from e
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if any(kw in str(e) for kw in _FATAL_KEYWORDS):
                raise MineruFatalError(str(e)) from e
            raise MineruTransientError(f"MinerU HTTP {resp.status_code}: {e}") from e
        j = resp.json()
        if j.get("code") != 0:
            err = f"MinerU 错误: code={j.get('code')} msg={j.get('msg')}"
            raise _classify(RuntimeError(err))
        return j["data"]

    async def _put_upload(self, upload_url: str, filename: str, data: bytes) -> None:
        print(f"  [MinerU] 上传 {filename} ({len(data)/1024:.0f}KB)...")
        try:
            async with self._upload_client() as http:
                resp = await http.put(upload_url, content=data)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise MineruTransientError(f"上传失败 {filename}: {e}") from e
        print(f"  [MinerU] {filename} 上传完成")

    def _api_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=None, http2=False, trust_env=False, timeout=API_TIMEOUT,
        )

    def _upload_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=None, http2=False, trust_env=False, timeout=UPLOAD_TIMEOUT,
        )

    # ── 对外接口（签名与旧 src/mineru_client.py 一致）────────────

    async def submit_batch(
        self,
        file_infos: list[dict],
        token: str,
    ) -> tuple[str, list[str]]:
        """使用指定 token 批量上传并提交解析。返回 (batch_id, md5_list)。"""
        files = []
        for fi in file_infos:
            files.append({
                "name": fi["name"],
                "is_ocr": self.s.mineru_enable_ocr,
                "data_id": fi["md5"],
            })

        body = {
            "files": files,
            "model_version": self.s.mineru_model_version,
            "enable_formula": self.s.mineru_enable_formula,
            "enable_table": self.s.mineru_enable_table,
            "language": self.s.mineru_language,
        }
        print(f"  [MinerU] 申请上传 URL ({len(files)} 个文件, key={token[:8]}...)...")
        data = await self._post("/api/v4/file-urls/batch", body, token=token)
        batch_id = data["batch_id"]
        file_urls: list[str] = data["file_urls"]
        print(f"  [MinerU] batch_id={batch_id}")

        errors = []
        for idx, fi in enumerate(file_infos):
            try:
                await self._put_upload(file_urls[idx], fi["name"], fi["data"])
            except Exception as e:
                err_msg = f"{fi['name']}: {e}"
                print(f"  [MinerU] 上传失败: {err_msg}")
                traceback.print_exc()
                errors.append(err_msg)

        if errors:
            raise MineruFatalError(
                f"上传失败 ({len(errors)}/{len(file_infos)}): {'; '.join(errors)}"
            )

        return batch_id, [fi["md5"] for fi in file_infos]

    async def poll_batch(self, batch_id: str, token: str) -> list[dict]:
        """使用指定 token 轮询批量任务结果"""
        from app.infrastructure.observability.instrument import tracked_span
        from app.interface.deps import get_container

        m = get_container().get_metrics()
        with tracked_span("mineru.poll", latency_metric=m.mineru_latency, error_metric=m.mineru_error_total):
            data = await self._get(f"/api/v4/extract-results/batch/{batch_id}", token=token)
        return data.get("extract_result", [])

    async def download_result(self, download_url: str) -> bytes:
        from app.infrastructure.observability.instrument import tracked_span
        from app.interface.deps import get_container

        m = get_container().get_metrics()
        with tracked_span("mineru.download", latency_metric=m.mineru_latency, error_metric=m.mineru_error_total):
            try:
                async with self._upload_client() as http:
                    resp = await http.get(download_url)
                    resp.raise_for_status()
                    return resp.content
            except httpx.HTTPError as e:
                raise MineruTransientError(f"下载解析结果失败: {e}") from e


def _auth_header(token: str) -> dict:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
