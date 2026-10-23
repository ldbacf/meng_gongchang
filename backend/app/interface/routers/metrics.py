"""Prometheus /metrics 端点（O-5.2 / T-5.3）。

暴露 `MetricsRegistry`（经 AppContainer.get_metrics() 单例）的 Prometheus 文本格式。

**采集点**：`MetricsRegistry` 里声明的 gauge 类指标（队列积压 / 额度剩余）没有天然的
写入方，必须在抓取时现取一次，否则它们永远是 0、告警规则永远不触发。
采集失败一律降级为「本次不更新」，不让监控把 /metrics 打挂。
"""
import logging

from fastapi import APIRouter
from fastapi.responses import Response

from app.interface.deps import get_container

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


async def _refresh_gauges(container) -> None:
    """抓取前刷新"需要主动查询"的 gauge：队列积压 + 各 key 额度剩余。"""
    metrics = container.get_metrics()

    try:
        depth = await container.get_queue().depth()
        metrics.queue_depth.labels(queue=container.get_settings().redis_queue).set(depth)
    except Exception as e:  # Redis 抖动不该影响其它指标
        logger.debug("queue_depth 采集失败: %s", e)

    try:
        km = container.get_key_manager()
        for token_id, remain in (await km.remaining_map()).items():
            metrics.quota_remaining.labels(key_id=token_id).set(remain)
    except Exception as e:
        logger.debug("quota_remaining 采集失败: %s", e)


@router.get("/metrics")
async def metrics():
    container = get_container()
    await _refresh_gauges(container)
    body = container.get_metrics().render()
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
