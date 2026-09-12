"""OTel 链路追踪（O-5.2 / T-5.5）。

- 默认全局 Provider 为无操作（no-op）；`init_tracing(exporter)` 配置带导出器的 Provider。
- 测试用 `init_tracing(exporter=InMemorySpanExporter())`，`get_spans()` 取 `_exporter.get_finished_spans()`
  断言一次调用产生的 span 集合（图节点 + 外部调用）。
- 生产可在 lifespan 配 ConsoleSpanExporter（逐 span 输出）或 OTLP exporter（延后到外部 collector）。
"""
from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_EXPORTER: SpanExporter | None = None


def init_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """配置全局 TracerProvider（幂等，仅首次生效）。`
    `exporter=None` 时用 InMemorySpanExporter（测试友好）；生产可用 SimpleSpanProcessor+Console/OTLP。
    """
    global _EXPORTER
    provider = TracerProvider()
    exp = exporter or InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace.set_tracer_provider(provider)
    _EXPORTER = exp
    return provider


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def get_spans() -> list:
    """返回已结束的 span 集合（InMemorySpanExporter 时）；未配置返回空列表。"""
    if isinstance(_EXPORTER, InMemorySpanExporter):
        return list(_EXPORTER.get_finished_spans())
    return []
