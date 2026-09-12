"""embedding-server — bge-m3 独立常驻服务。

动机：原每个 API/worker 进程各自加载一份 4.3G bge-m3（≈5 份 ≈11.5G，且每次重启重载）。
本服务把模型剥离为**单进程常驻**，API/worker 经 HTTP 调 `/embed`、`/embed/batch`。
模型 `get_sentence_transformer()` 懒加载：**首个请求才加载一次**，此后常驻。

- 复用现有 `EmbeddingFactory`（本地 models/bge-m3 优先），零新镜像/零模型格式转换。
- 同步端点（FastAPI 自动线程池），CPU 推理不阻塞事件循环。
- `normalize_embeddings=True` + `settings.embedding_dim(1024)`，与 Milvus schema / 检索端一致。

入口:
    python -m app.application.embedding_server        # or `uv run embedding-server`
    uv run uvicorn app.application.embedding_server:app --host 0.0.0.0 --port 8084
"""
from __future__ import annotations

import threading

from fastapi import FastAPI
from pydantic import BaseModel

from app.infrastructure.adapters.embedding import EmbeddingFactory
from app.infrastructure.settings import get_settings

app = FastAPI(title="embedding-service", version="0.1")

_factory = EmbeddingFactory()
_model = None
_lock = threading.Lock()


def _get_model():
    """懒加载 bge-m3（首个请求加载一次，此后常驻；线程安全）。"""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _factory.get_sentence_transformer()
    return _model


class EmbedRequest(BaseModel):
    text: str


class EmbedBatchRequest(BaseModel):
    texts: list[str]


@app.get("/health")
async def health():
    """就绪探测 + 维度上报（API 启动时经 HttpEmbeddingPort.check_health 调用）。"""
    return {"status": "ok", "dim": get_settings().embedding_dim}


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
