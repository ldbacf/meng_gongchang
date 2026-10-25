"""HTTP 访问日志中间件 —— 每个请求一行 JSON。

## 为什么需要它

之前 API 只有 uvicorn 自带的访问日志（`INFO: 127.0.0.1:xxxxx - "GET ... 200 OK"`），
信息量只有"状态码"，看不出：慢在哪、谁调的、哪个会话/知识库。

而项目自身的 `logger.info` 全后端只有 4 处，等于没有业务日志。

本中间件在**请求边界**统一补一条结构化记录，字段与 `observability/logger.py`
的 JSON 格式一致（`ctx` 里带 method/path/status/耗时），便于 grep 与后续接入
Prometheus/Loki 之外的人肉排查。

## 噪音控制

`/health`、`/metrics`、`/openapi.json`、`/docs` 这类探针/静态端点降到 DEBUG，
默认 INFO 级别下不打印 —— 否则 30 秒一次的健康检查会把真正的请求刷没。
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.observability.logger import get_logger

logger = get_logger("app.access")

#: 这些路径只在 DEBUG 级打印（探针 / 文档 / 静态）
QUIET_PATHS = ("/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/favicon.ico")

#: 超过这个耗时就升级为 WARNING，方便一眼看出慢请求
SLOW_MS = 3000.0


def _is_quiet(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in QUIET_PATHS)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 未处理异常：先记一条带路径的 error，再把异常抛给上层（保持 500 语义）
            logger.error(
                "请求异常",
                exc_info=True,
                extra={
                    "ctx": {
                        "method": request.method,
                        "path": request.url.path,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            raise

        ms = round((time.perf_counter() - started) * 1000, 1)
        ctx = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": ms,
        }
        # 查询串单独放，避免把 path 弄脏（日志里 path 便于聚合统计）
        if request.url.query:
            ctx["query"] = request.url.query

        if _is_quiet(request.url.path):
            logger.debug("请求", extra={"ctx": ctx})
        elif ms >= SLOW_MS or response.status_code >= 500:
            logger.warning("慢请求/服务端错误", extra={"ctx": ctx})
        else:
            logger.info("请求", extra={"ctx": ctx})

        return response
