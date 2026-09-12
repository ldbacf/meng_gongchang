"""T-5.6 — PDF 代理流 Range 断点支持。

单元测试 `_pdf_range_bounds`（Range 语义）：206 + Content-Range、416 越界、200 全量。
（端点 `stream_document_pdf` 已用该 helper；完整 MinIO 代理流由手动端到端验证。）
"""
from __future__ import annotations

from src.main import _pdf_range_bounds


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
