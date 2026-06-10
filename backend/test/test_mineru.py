"""
MinerU API 测试脚本 (v4)
支持本地文件上传解析（单文件/批量）和 URL 直接解析。

用法:
    python test_mineru.py --file after/xxx.pdf
    python test_mineru.py --batch
    python test_mineru.py -u "https://example.com/doc.pdf"
    python test_mineru.py --batch-url "https://a.com/1.pdf" "https://a.com/2.pdf"
"""

import asyncio
import io
import os
import time
import zipfile
from argparse import ArgumentParser
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── 配置 ────────────────────────────────────────────────────
API_BASE = os.getenv("MINERU_API_BASE", "https://mineru.net").rstrip("/")
API_TOKEN = os.getenv("MINERU_API_TOKEN", "")
MODEL_VERSION = os.getenv("MINERU_MODEL_VERSION", "vlm")
ENABLE_OCR = os.getenv("ENABLE_OCR", "false").lower() == "true"
ENABLE_FORMULA = os.getenv("ENABLE_FORMULA", "true").lower() == "true"
ENABLE_TABLE = os.getenv("ENABLE_TABLE", "true").lower() == "true"
LANGUAGE = os.getenv("LANGUAGE", "ch")

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PDF_INPUT_DIR = Path(os.getenv("PDF_INPUT_DIR", SCRIPT_DIR / "after"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", SCRIPT_DIR / "ok"))

AUTH_HEADER = {"Content-Type": "application/json", "Authorization": f"Bearer {API_TOKEN}"}

POLL_INTERVAL = 3
MAX_POLL_TIME = 600
CHUNK_SIZE = 50  # API 单次最多 50 个文件


STATE_LABELS = {
    "waiting-file": "等待上传",
    "pending":      "排队中",
    "running":      "解析中",
    "converting":   "格式转换中",
    "done":         "已完成",
    "failed":       "失败",
}


# ── 工具函数 ────────────────────────────────────────────────

def extract_zip_to(zip_bytes: bytes, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.namelist():
            target = dest / member
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
    print(f"  [OK] 解压完成 -> {dest}")


# ── HTTP 客户端 ─────────────────────────────────────────────

def _make_client(connect_timeout: float = 30.0) -> httpx.AsyncClient:
    """创建不走系统代理的 httpx 客户端"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=connect_timeout),
        proxy=None,
        http2=False,
        trust_env=False,
    )


async def _post(path: str, body: dict, timeout: float = 30.0) -> dict:
    async with _make_client(timeout) as http:
        resp = await http.post(f"{API_BASE}{path}", headers=AUTH_HEADER, json=body)
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0:
            raise RuntimeError(f"API 错误: code={j.get('code')} msg={j.get('msg')}")
        return j["data"]


async def _get(path: str, timeout: float = 30.0) -> dict:
    async with _make_client(timeout) as http:
        resp = await http.get(f"{API_BASE}{path}", headers=AUTH_HEADER)
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0:
            raise RuntimeError(f"API 错误: code={j.get('code')} msg={j.get('msg')}")
        return j["data"]


async def _put_upload(upload_url: str, file_path: Path) -> None:
    """PUT 上传文件到 OSS 预签名 URL (不设 Content-Type)"""
    with open(file_path, "rb") as f:
        body = f.read()
    async with _make_client() as http:
        resp = await http.put(upload_url, content=body)
        resp.raise_for_status()


async def _download_zip(url: str) -> bytes:
    async with _make_client() as http:
        resp = await http.get(url)
        resp.raise_for_status()
        return resp.content


# ── 核心流程 ────────────────────────────────────────────────

def _make_file_entry(path: Path) -> dict:
    """构建单个文件条目，每文件一个唯一 data_id 用于追踪"""
    return {
        "name": path.name,
        "is_ocr": ENABLE_OCR,
        "data_id": path.stem,
    }


def _make_batch_body(files: list[dict], **overrides) -> dict:
    return {
        "files": files,
        "model_version": overrides.get("model_version", MODEL_VERSION),
        "enable_formula": overrides.get("enable_formula", ENABLE_FORMULA),
        "enable_table": overrides.get("enable_table", ENABLE_TABLE),
        "language": overrides.get("language", LANGUAGE),
    }


async def batch_upload_and_wait(
    file_paths: list[Path],
    output_parent: Path,
) -> dict[str, bool]:
    """
    本地文件批量上传并等待解析完成。
    通过 file.data_id 追踪每个文件，避免文件名冲突。
    返回 {data_id: 是否成功}
    """
    total = len(file_paths)
    entries = [_make_file_entry(p) for p in file_paths]
    data_id_to_path = {e["data_id"]: file_paths[i] for i, e in enumerate(entries)}
    results: dict[str, bool] = {}

    # 1. 申请上传链接
    print(f"[1/3] 申请上传链接 ({total} 个文件)...")
    body = _make_batch_body(entries)
    data = await _post("/api/v4/file-urls/batch", body)
    batch_id = data["batch_id"]
    file_urls: list[str] = data["file_urls"]
    print(f"  batch_id: {batch_id}")

    # 2. 并发上传 (PUT 不加 Content-Type)
    print(f"[2/3] 上传文件中...")

    async def upload_one(idx: int):
        path = file_paths[idx]
        url = file_urls[idx]
        try:
            await _put_upload(url, path)
            print(f"  [OK] {path.name}")
            return True
        except Exception as e:
            print(f"  [FAIL] {path.name}: {e}")
            return False

    upload_results = await asyncio.gather(*[upload_one(i) for i in range(total)])
    failed_uploads = [file_paths[i].name for i, ok in enumerate(upload_results) if not ok]
    if failed_uploads:
        print(f"  {len(failed_uploads)} 个上传失败: {failed_uploads}")

    if all(not ok for ok in upload_results):
        print("  全部上传失败，退出")
        return {e["data_id"]: False for e in entries}

    # 3. 轮询批量结果 (用 data_id 追踪)
    print(f"[3/3] 等待解析完成...")
    start = time.time()
    pending = {e["data_id"] for e in entries}

    while pending and (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start
        try:
            data = await _get(f"/api/v4/extract-results/batch/{batch_id}")
        except Exception as e:
            print(f"  ... 查询失败 ({elapsed:.0f}s): {e}")
            continue

        for item in data.get("extract_result", []):
            did = item.get("data_id") or item["file_name"]
            state = item["state"]

            if did not in pending:
                continue

            progress = ""
            if "extract_progress" in item:
                ep = item["extract_progress"]
                progress = (
                    f" [{ep.get('extracted_pages', '?')}/"
                    f"{ep.get('total_pages', '?')}p]"
                )

            fname = item.get("file_name", did)
            label = STATE_LABELS.get(state, state)
            print(f"  {fname}: {label}{progress} ({elapsed:.0f}s)")

            if state == "done":
                try:
                    zip_bytes = await _download_zip(item["full_zip_url"])
                    dest = output_parent / Path(fname).stem
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, extract_zip_to, zip_bytes, dest)
                    results[did] = True
                except Exception as e:
                    print(f"    [FAIL] 下载/解压: {e}")
                    results[did] = False
                pending.discard(did)

            elif state == "failed":
                print(f"    [FAIL] 解析: {item.get('err_msg', '')}")
                results[did] = False
                pending.discard(did)

    for did in pending:
        fname = data_id_to_path.get(did, Path(did)).name
        print(f"  [FAIL] {fname}: 超时未完成")
        results[did] = False

    return results


async def url_single_task(file_url: str, output_dir: Path):
    """URL 单文件直接解析"""
    print(f"[1/2] 提交解析: {file_url}")
    data = await _post("/api/v4/extract/task", {
        "url": file_url,
        "model_version": MODEL_VERSION,
        "is_ocr": ENABLE_OCR,
        "enable_formula": ENABLE_FORMULA,
        "enable_table": ENABLE_TABLE,
        "language": LANGUAGE,
    })
    task_id = data["task_id"]
    print(f"  task_id: {task_id}")

    print("[2/2] 等待解析...")
    start = time.time()
    while (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start
        result = await _get(f"/api/v4/extract/task/{task_id}")
        state = result["state"]
        label = STATE_LABELS.get(state, state)
        print(f"  ... {label} ({elapsed:.0f}s)")

        if state == "done":
            zip_bytes = await _download_zip(result["full_zip_url"])
            extract_zip_to(zip_bytes, output_dir)
            return
        if state == "failed":
            raise RuntimeError(f"解析失败: {result.get('err_msg', '')}")
    raise TimeoutError(f"超时 ({MAX_POLL_TIME}s)")


async def url_batch_task(file_urls: list[str], output_parent: Path):
    """URL 批量解析 — 通过 data_id 追踪每个文件"""
    print(f"[1/2] 提交批量 URL ({len(file_urls)} 个)...")
    files = [{"url": u, "data_id": f"url_{i}"} for i, u in enumerate(file_urls)]
    body = _make_batch_body(files)
    data = await _post("/api/v4/extract/task/batch", body)
    batch_id = data["batch_id"]
    print(f"  batch_id: {batch_id}")

    print("[2/2] 等待解析...")
    start = time.time()
    pending: dict[str, str] = {f"url_{i}": u for i, u in enumerate(file_urls)}

    while pending and (time.time() - start) < MAX_POLL_TIME:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed = time.time() - start
        data = await _get(f"/api/v4/extract-results/batch/{batch_id}")

        for item in data.get("extract_result", []):
            did = item.get("data_id")
            if did not in pending:
                continue

            fname = item.get("file_name", did)
            state = item["state"]
            label = STATE_LABELS.get(state, state)
            print(f"  {fname}: {label} ({elapsed:.0f}s)")

            if state == "done":
                zip_bytes = await _download_zip(item["full_zip_url"])
                dest = output_parent / Path(fname).stem
                extract_zip_to(zip_bytes, dest)
                pending.pop(did, None)
            elif state == "failed":
                print(f"    [FAIL] {item.get('err_msg', '')}")
                pending.pop(did, None)

    if pending:
        print(f"  [FAIL] {len(pending)} 个超时: {list(pending.values())}")


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = ArgumentParser(description="MinerU API 测试工具 (v4)")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", "-f", type=str, help="本地 PDF 路径 (单文件)")
    mode.add_argument("--batch", "-b", action="store_true",
                      help="扫描 after/ 目录下所有 PDF")
    mode.add_argument("--file-url", "-u", type=str,
                      help="直接提供 PDF URL (跳过上传)")
    mode.add_argument("--batch-url", nargs="+", type=str,
                      help="多个 PDF URL 批量解析")

    parser.add_argument("--output", "-o", type=str, default=None,
                        help="输出目录 (默认 ok/)")
    parser.add_argument("--model", "-m", type=str, default=None,
                        help="模型: pipeline / vlm / MinerU-HTML")
    parser.add_argument("--ocr", action="store_true", default=None, help="启用 OCR")
    parser.add_argument("--no-formula", action="store_true", help="禁用公式识别")
    parser.add_argument("--no-table", action="store_true", help="禁用表格识别")
    parser.add_argument("--lang", type=str, default=None,
                        help="语言代码 (ch/en/ja/ko)")

    args = parser.parse_args()

    global MODEL_VERSION, ENABLE_OCR, ENABLE_FORMULA, ENABLE_TABLE, LANGUAGE
    if args.model:
        MODEL_VERSION = args.model
    if args.ocr is not None:
        ENABLE_OCR = args.ocr
    if args.no_formula:
        ENABLE_FORMULA = False
    if args.no_table:
        ENABLE_TABLE = False
    if args.lang:
        LANGUAGE = args.lang

    out = Path(args.output) if args.output else OUTPUT_DIR

    if args.file_url:
        print(f"URL 单文件模式: {args.file_url}")
        asyncio.run(url_single_task(args.file_url, out))

    elif args.batch_url:
        print(f"URL 批量模式: {len(args.batch_url)} 个链接")
        asyncio.run(url_batch_task(args.batch_url, out))

    elif args.batch:
        pdfs = sorted(PDF_INPUT_DIR.glob("*.pdf"))
        if not pdfs:
            print(f"[FAIL] 目录 {PDF_INPUT_DIR} 下没有 PDF 文件")
            return
        print(f"本地批量模式: {len(pdfs)} 个 PDF")
        print(f"模型={MODEL_VERSION} OCR={ENABLE_OCR} 公式={ENABLE_FORMULA} "
              f"表格={ENABLE_TABLE} 语言={LANGUAGE}")
        print("-" * 60)

        total_ok = 0
        for i in range(0, len(pdfs), CHUNK_SIZE):
            chunk = pdfs[i:i + CHUNK_SIZE]
            print(f"\n--- 批次 {i // CHUNK_SIZE + 1} ({len(chunk)} 个文件) ---")
            r = asyncio.run(batch_upload_and_wait(chunk, out))
            total_ok += sum(1 for v in r.values() if v)

        print(f"\n全部完成: {total_ok}/{len(pdfs)} 成功")

    else:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = SCRIPT_DIR / file_path
        if not file_path.exists():
            print(f"[FAIL] 文件不存在: {file_path}")
            return
        print(f"本地单文件模式: {file_path.name}")
        print(f"模型={MODEL_VERSION} OCR={ENABLE_OCR} 公式={ENABLE_FORMULA} "
              f"表格={ENABLE_TABLE} 语言={LANGUAGE}")
        print("-" * 60)
        r = asyncio.run(batch_upload_and_wait([file_path], out))
        ok = sum(1 for v in r.values() if v)
        print(f"\n完成: {ok}/{len(r)} 成功")


if __name__ == "__main__":
    main()
