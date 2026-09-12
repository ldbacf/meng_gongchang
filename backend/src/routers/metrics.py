"""Prometheus /metrics 端点（O-5.2 / T-5.3）。

暴露 `MetricsRegistry`（经 AppContainer.get_metrics() 单例）的 Prometheus 文本格式。
"""
from fastapi import APIRouter
from fastapi.responses import Response

from app.interface.deps import get_container

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics():
    body = get_container().get_metrics().render()
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
