"""
阶段一管线测试 — 端到端验证 FastAPI + MinerU + Worker 全流程

前置:
  1. docker compose up -d       (启动 PostgreSQL / Redis / MinIO)
  2. uv run uvicorn src.main:app --port 8000   (启动 API)
  3. uv run python -m src.worker               (启动 Worker)

用法:
  uv run python test_pipeline.py
  uv run python test_pipeline.py --file "after/xxx.pdf"
"""

import asyncio
import hashlib
import time
from argparse import ArgumentParser
from pathlib import Path

import httpx

API = "http://localhost:8000"
SCRIPT_DIR = Path(__file__).resolve().parent

# 颜色输出 (兼容 Windows cmd)
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def ok(msg):   print(f"{GREEN}[OK]{RESET} {msg}")
def fail(msg): print(f"{RED}[FAIL]{RESET} {msg}")
def info(msg): print(f"{CYAN}[INFO]{RESET} {msg}")
def hr():      print("-" * 60)


async def test_health():
    """健康检查"""
    info("检查 API 健康状态...")
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{API}/health")
        assert r.status_code == 200, f"API 不可达: {r.status_code}"
        ok("API 正常")


async def test_upload_single(pdf_path: Path):
    """单文件上传 → 查看状态 → 等 Worker 处理完成"""
    if not pdf_path.exists():
        fail(f"文件不存在: {pdf_path}")
        return

    info(f"上传文件: {pdf_path.name}")
    with open(pdf_path, "rb") as f:
        pdf_data = f.read()

    file_md5 = hashlib.md5(pdf_data).hexdigest()
    info(f"文件 MD5: {file_md5}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as c:
        # 1. 上传
        r = await c.post(
            f"{API}/api/v1/documents",
            files={"file": (pdf_path.name, pdf_data, "application/pdf")},
        )
        if r.status_code == 200:
            data = r.json()
            doc_id = data["id"]
            ok(f"上传成功: id={doc_id} status={data['status']} msg={data['message']}")
        else:
            fail(f"上传失败: {r.status_code} {r.text}")
            return

        # 2. 查询状态
        info("查询任务状态...")
        r = await c.get(f"{API}/api/v1/documents/{doc_id}")
        data = r.json()
        info(f"  状态: {data['status']}")

        # 3. 通过 MD5 查重
        info("MD5 查重测试...")
        r = await c.get(f"{API}/api/v1/documents/md5/{file_md5}")
        if r.status_code == 200:
            data = r.json()
            ok(f"MD5 命中: id={data['id']} status={data['status']}")
        else:
            fail(f"MD5 查重失败: {r.status_code}")

        # 4. 再次上传相同文件 → 验证秒传
        info("验证秒传逻辑 (再次上传相同文件)...")
        with open(pdf_path, "rb") as f:
            r = await c.post(
                f"{API}/api/v1/documents",
                files={"file": (pdf_path.name, f.read(), "application/pdf")},
            )
        if r.status_code == 200:
            data = r.json()
            ok(f"秒传生效: {data['message']}")
        else:
            fail(f"秒传验证失败: {r.status_code} {r.text}")

        # 5. 等待 Worker 完成
        info("等待 Worker 解析完成...")
        start = time.time()
        while (time.time() - start) < 600:
            await asyncio.sleep(5)
            r = await c.get(f"{API}/api/v1/documents/{doc_id}")
            data = r.json()
            elapsed = time.time() - start
            info(f"  状态: {data['status']} ({elapsed:.0f}s)")

            if data["status"] == "parsed":
                ok(f"解析完成! parsed_minio_path={data['parsed_minio_path']}")
                return
            if data["status"] == "failed":
                fail(f"解析失败: {data.get('error_msg', '')}")
                return

        fail("超时: Worker 未在 600s 内完成")


async def test_upload_batch(pdf_paths: list[Path]):
    """批量上传测试"""
    info(f"批量上传 {len(pdf_paths)} 个文件...")

    files = []
    for p in pdf_paths:
        if p.exists():
            files.append(
                ("files", (p.name, p.read_bytes(), "application/pdf"))
            )

    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as c:
        r = await c.post(f"{API}/api/v1/documents/batch", files=files)
        if r.status_code == 200:
            data = r.json()
            for item in data:
                ok(f"  {item['original_name']}: {item['message']}")
        else:
            fail(f"批量上传失败: {r.status_code} {r.text}")


async def main():
    parser = ArgumentParser(description="阶段一管线测试")
    parser.add_argument("--file", "-f", type=str, default=None,
                        help="指定单个 PDF 文件路径 (默认测试 after/ 下第一个)")
    parser.add_argument("--batch", "-b", action="store_true",
                        help="批量测试 after/ 下所有 PDF")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print("   MinerU Pipeline Phase 1 — 端到端测试")
    print(f"{'=' * 60}\n")

    try:
        await test_health()
    except Exception as e:
        fail(f"API 未启动: {e}")
        return

    hr()

    if args.batch:
        pdfs = sorted((SCRIPT_DIR / "after").glob("*.pdf"))
        if not pdfs:
            fail("after/ 下无 PDF 文件")
            return
        await test_upload_batch(pdfs)
    else:
        if args.file:
            file_path = Path(args.file)
            if not file_path.is_absolute():
                file_path = SCRIPT_DIR / file_path
        else:
            pdfs = sorted((SCRIPT_DIR / "after").glob("*.pdf"))
            if not pdfs:
                fail("after/ 下无 PDF 文件，请用 --file 指定")
                return
            file_path = pdfs[0]

        await test_upload_single(file_path)

    hr()
    print(f"\n{GREEN}测试完成{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
