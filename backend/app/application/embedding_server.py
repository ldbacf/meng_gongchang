"""embedding-server — bge-m3 独立常驻服务。

动机：原每个 API/worker 进程各自加载一份 4.3G bge-m3（≈5 份 ≈11.5G，且每次重启重载）。
本服务把模型剥离为**单进程常驻**，API/worker 经 HTTP 调 `/embed`、`/embed/batch`。
模型在**启动时（lifespan）加载一次**，此后常驻——第一个用户不必替整个服务等加载。

- 复用现有 `EmbeddingFactory`（本地 models/bge-m3 优先），零新镜像/零模型格式转换。
- 同步端点（FastAPI 自动线程池），CPU 推理不阻塞事件循环。
- `normalize_embeddings=True` + `settings.embedding_dim(1024)`，与 Milvus schema / 检索端一致。

入口:
    python -m app.application.embedding_server        # or `uv run embedding-server`
    uv run uvicorn app.application.embedding_server:app --host 0.0.0.0 --port 8084
"""
from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.infrastructure.adapters.embedding import EmbeddingFactory
from app.infrastructure.settings import get_settings

_factory = EmbeddingFactory()
_model = None
_lock = threading.Lock()


def _get_model():
    """加载 bge-m3（线程安全，只加载一次后常驻）。

    启动时由 `lifespan` 主动调用一次（见下）；`_lock` + 双重检查保留，
    使测试/异常路径下首次请求仍能安全触发加载。
    """
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _factory.get_sentence_transformer()
    return _model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """**启动即加载模型**（而非等首个请求）。

    常驻服务的意义就是"模型只加载一次"，但那一次不该让第一个用户等
    （本来表现为首个问答凭空多等数秒~数十秒）。

    放在 lifespan（启动阶段）的副作用（已实测）：uvicorn 在 lifespan 启动完成前
    **不接收连接**，所以加载期间 `/health` 是连不上而不是答 `loading` —— 对调用方
    而言同样是"未就绪"，语义没问题；而模型加载失败会让启动直接失败（fail-fast），
    优于留一个"起来了但一请求就 500"的进程。`/health` 的 `status="loading"` 分支
    仅在"服务已接收连接但模型仍未就绪"时才会走到（如绕过 lifespan 的场景）。

    走 `asyncio.to_thread`：加载不占用事件循环线程。
    """
    t0 = time.perf_counter()
    print("[embedding] 加载 bge-m3 ...（首次启动较慢，属正常）", flush=True)
    await asyncio.to_thread(_get_model)
    print(f"[embedding] bge-m3 就绪，用时 {time.perf_counter() - t0:.1f}s", flush=True)
    yield


app = FastAPI(title="embedding-service", version="0.1", lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str


class EmbedBatchRequest(BaseModel):
    texts: list[str]


@app.get("/health")
async def health():
    """就绪探测 + 维度上报（API 启动时经 HttpEmbeddingPort.check_health 调用）。

    `status` 只有在模型真正加载完成后才是 `ok`，否则 `loading` —— 客户端
    `check_health` 以 `status == "ok"` 为判据，所以不会把"服务在跑但模型没就绪"
    误判成就绪。客户端无需改动。
    """
    return {
        "status": "ok" if _model is not None else "loading",
        "dim": get_settings().embedding_dim,
    }


@app.post("/embed")
def embed(req: EmbedRequest):
    """单条编码（sync → 线程池执行，不阻塞事件循环）。"""
    vec = _get_model().encode([req.text], normalize_embeddings=True)[0]
    return {"embedding": vec.tolist()}


@app.post("/embed/batch")
def embed_batch(req: EmbedBatchRequest):
    """批量编码（整篇数十秒级，客户端超时已放宽）。"""
    vecs = _get_model().encode(req.texts, normalize_embeddings=True)
    return {"embeddings": [v.tolist() for v in vecs]}


def run() -> None:
    """`embedding-server` 脚本入口（uvicorn 起服务，端口 8084）。"""
    import uvicorn

    uvicorn.run("app.application.embedding_server:app", host="0.0.0.0", port=8084)


if __name__ == "__main__":
    run()
