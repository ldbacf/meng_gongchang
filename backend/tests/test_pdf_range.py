"""T-5.6 — PDF 代理流 Range 断点支持。

单元测试 `_pdf_range_bounds`（Range 语义）：206 + Content-Range、416 越界、200 全量。
另含路由契约测试：端点必须同时接受 GET 与 HEAD（pdf.js 靠 HEAD 探测分片能力）。
（完整 MinIO 代理流由手动端到端验证。）
"""
from __future__ import annotations

from app.main import _pdf_range_bounds


def test_full_when_no_range():
    offset, length, status, headers = _pdf_range_bounds("", 1000)
    assert (offset, length, status) == (0, 1000, 200)
    assert headers == {}


def test_partial_range_206():
    offset, length, status, headers = _pdf_range_bounds("bytes=0-1023", 5000)
    assert (offset, length, status) == (0, 1024, 206)
    assert headers["Content-Range"] == "bytes 0-1023/5000"


def test_partial_range_open_ended():
    offset, length, status, headers = _pdf_range_bounds("bytes=200-", 1000)
    assert (offset, length, status) == (200, 800, 206)
    assert headers["Content-Range"] == "bytes 200-999/1000"


def test_partial_range_clamp_to_size():
    offset, length, status, headers = _pdf_range_bounds("bytes=900-2000", 1000)
    assert (offset, length, status) == (900, 100, 206)
    assert headers["Content-Range"] == "bytes 900-999/1000"


def test_out_of_bounds_416():
    offset, length, status, headers = _pdf_range_bounds("bytes=4000-", 1000)
    assert status == 416
    assert headers["Content-Range"] == "bytes */1000"


def test_suffix_range():
    offset, length, status, headers = _pdf_range_bounds("bytes=-500", 1000)
    assert (offset, length, status) == (500, 500, 206)
    assert headers["Content-Range"] == "bytes 500-999/1000"


# ── 路由契约：GET + HEAD ────────────────────────────────────────


def _pdf_route_methods() -> set[str]:
    """汇总 /pdf/stream 上所有方法（GET 与 HEAD 是两条独立 APIRoute）。"""
    from app.main import app

    methods: set[str] = set()
    for r in app.routes:
        if getattr(r, "path", "").endswith("/pdf/stream"):
            methods |= set(getattr(r, "methods", set()) or set())
    return methods


def test_pdf_stream_route_accepts_head():
    """端点必须能响应 HEAD。

    回归：只声明 `@router.get` 时 HEAD 会 405，pdf.js 探测失败 → 退回整份下载，
    分片加载失效（前端表现为必须等整份 PDF 到齐才出第一页）。

    注意 GET 与 HEAD 现在是**两条独立 APIRoute**：曾用
    `@router.api_route(methods=["GET","HEAD"])` 一条挂两个方法，但那会让 FastAPI
    的默认 `generate_unique_id` 只取第一个方法名，两个方法的 operationId 完全相同，
    OpenAPI 出现重复 ID，`openapi-typescript` 生成的类型直接 TS2300、前端类型检查失败。
    所以这里按「所有 /pdf/stream 路由的方法并集」判断，而不是只看第一条。
    """
    methods = _pdf_route_methods()
    assert methods, "未找到 /pdf/stream 路由"
    assert "GET" in methods
    assert "HEAD" in methods, "缺少 HEAD：pdf.js 无法探测 Size/Range 能力"
