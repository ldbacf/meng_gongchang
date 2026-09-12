"""外部调用/节点插桩工具（O-5.2）。

- `tracked_span(name, latency_metric, error_metric, backend)`：上下文管理器 —— 包裹一次
  外部调用/节点，创建 OTel span + 记录 latency 直方图 + 异常时 error 计数器 +1 并重抛。
- `@decorate_tracked(...)`：同步/异步函数装饰器，等价地包裹整个函数体。

用法：
    with tracked_span("milvus.search", latency_metric=m.milvus_latency, backend=None):
        ...external call...
    或 @decorate_tracked("rerank", latency_metric=m.rerank_latency) 包住函数。
"""
from __future__ import annotations

import functools
import time
from contextlib import contextmanager

from app.infrastructure.observability.tracing import get_tracer


def _finish(span, latency_metric, error_metric, backend, start, exc):
    if exc is not None:
        span.set_attribute("status", "error")
        span.record_exception(exc)
        if error_metric is not None:
            error_metric.inc()
    else:
        span.set_attribute("status", "ok")
    elapsed = time.perf_counter() - start
    if latency_metric is not None:
        if backend is not None and hasattr(latency_metric, "labels"):
            latency_metric.labels(backend=backend).observe(elapsed)
        else:
            latency_metric.observe(elapsed)
    span.end()


@contextmanager
def tracked_span(name: str, *, latency_metric=None, error_metric=None, backend=None):
    span = get_tracer("medrag").start_span(name)
    start = time.perf_counter()
    exc = None
    try:
        yield span
    except Exception as e:
        exc = e
        raise
    finally:
        _finish(span, latency_metric, error_metric, backend, start, exc)


def decorate_tracked(name: str, *, latency_metric=None, error_metric=None, backend=None):
    """函数装饰器：同步/异步函数体整体包裹为一个 span（含 latency/error 计量）。"""

    def _wrap(fn):
        @functools.wraps(fn)
        def _sync(*args, **kwargs):
            with tracked_span(name, latency_metric=latency_metric, error_metric=error_metric, backend=backend):
                return fn(*args, **kwargs)

        @functools.wraps(fn)
        async def _async(*args, **kwargs):
            with tracked_span(name, latency_metric=latency_metric, error_metric=error_metric, backend=backend):
                return await fn(*args, **kwargs)

        return _async if asyncio.iscoroutinefunction(fn) else _sync

    import asyncio

    return _wrap
