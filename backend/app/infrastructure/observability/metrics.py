"""Prometheus 指标注册表（O-5.2 / 契约 4.2.1 / T-5.3）。

- `MetricsRegistry` 集中声明对外暴露的指标，经 `AppContainer.get_metrics()` 单例注入。
- `/metrics` 由 `app/interface/routers/metrics.py` 调用 `registry.render()` 输出（prometheus_client 文本格式）。
- 指标命名与契约 4.2.1 对齐：图节点耗时 / RAG 量与降级 / 检索·重排·LLM·MinerU 耗时 /
  队列深度 / 额度剩余·拒绝 / LLM·MinerU 错误率。
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class MetricsRegistry:
    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or CollectorRegistry()
        r = self._registry

        # 图/管线
        self.graph_node_duration = Histogram(
            "graph_node_duration_seconds", "图节点耗时（秒）", ["graph", "node"], registry=r,
        )
        self.rag_total = Counter("rag_total", "问答总量", registry=r)
        self.rag_degraded_total = Counter("rag_degraded_total", "按步降级量", ["step"], registry=r)

        # 检索/外部调用 延迟
        self.retrieval_latency = Histogram(
            "retrieval_latency_seconds", "检索后端耗时（秒）", ["backend"], registry=r,
        )
        self.rerank_latency = Histogram("rerank_latency_seconds", "rerank 耗时（秒）", registry=r)
        self.llm_latency = Histogram("llm_latency_seconds", "LLM 耗时（秒）", registry=r)
        self.mineru_latency = Histogram("mineru_latency_seconds", "MinerU 耗时（秒）", registry=r)

        # 容量/可靠性
        self.queue_depth = Gauge("queue_depth", "队列深度", ["queue"], registry=r)
        self.quota_remaining = Gauge("quota_remaining", "额度剩余", ["key_id"], registry=r)
        self.quota_rejected_total = Counter("quota_rejected_total", "额度拒绝总量", registry=r)
        self.llm_error_total = Counter("llm_error_total", "LLM 错误总量", registry=r)
        self.mineru_error_total = Counter("mineru_error_total", "MinerU 错误总量", registry=r)

    def render(self) -> bytes:
        from prometheus_client import generate_latest

        return generate_latest(self._registry)
