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


def _pdf_route():
    """取出 /pdf/stream 的 APIRoute 对象。"""
    from app.main import app

    for r in app.routes:
        if getattr(r, "path", "").endswith("/pdf/stream"):
            return r
    return None


def test_pdf_stream_route_accepts_head():
    """端点必须声明 HEAD。

    回归：只声明 `@router.get` 时 HEAD 会 405，pdf.js 探测失败 → 退回整份下载，
    分片加载失效（前端表现为必须等整份 PDF 到齐才出第一页）。
    """
    route = _pdf_route()
    assert route is not None, "未找到 /pdf/stream 路由"
    assert "GET" in route.methods
    assert "HEAD" in route.methods, "缺少 HEAD：pdf.js 无法探测 Size/Range 能力"
