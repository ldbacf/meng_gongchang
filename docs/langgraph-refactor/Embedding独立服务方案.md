# Embedding 独立服务方案（bge-m3 常驻）

> 归属：`docs/langgraph-refactor/Embedding独立服务方案.md`
> 决策：**自写 FastAPI wrapper**（用户 2026-08-16 确认）；本机无 GPU，bge-m3 走 CPU。
> 性质：架构决策文档（非阶段任务）；实施可并入阶段 4/5 或单独立项。

---

## 一、动机（为什么做）

当前 bge-m3 嵌入模型在**每个进程内各自加载一份**，且每份在进程启动时通过 `container.start()` 重新加载一次，代价巨大：

| 项 | 现状 |
| --- | --- |
| 模型目录 | `backend/models/bge-m3/` ≈ **4.3G**（`pytorch_model.bin` 2.27G fp32 + `onnx/` 2.2G；已 gitignore，不入库） |
| 每份内存 | bge-m3 fp32 ≈ **2.3G** |
| 进程副本数 | `uvicorn --workers 4`（4 个 API 进程）+ `pipeline-worker` 独立进程 = **5 份** |
| 合计内存 | 5 × 2.3G ≈ **~11.5G**，且每次后端重启 5 个进程各自重新加载一次 |
| 启动阻塞 | `container.start()` L317 `get_hf_embeddings()` 同步加载，阻塞事件循环（模型加载数百 MB→GB） |

**目标**：把 bge-m3 从 API / worker 进程剥离，独立为一个**长驻服务**——模型只加载一次，API/worker 经 HTTP 调用，消除重复加载与重复内存占用。

**顺带收益**：
- API / worker 启动变快（不再等模型加载，只做远端健康检查）。
- 多进程共享同一模型实例，内存从 ~11.5G 降到 **1 份 ≈ 2.3G**（+ 服务自身开销）。
- 未来若上 GPU，只需替换服务端推理内核，API/worker 零改动。

---

## 二、方案总览（架构）

```
┌──────────── embed-service（独立进程，模型常驻）────────────┐
│  FastAPI + EmbeddingFactory.get_sentence_transformer()     │
│  POST /embed      单条：{text} → {embedding: [1024]}       │
│  POST /embed/batch 批量：{texts:[...]} → {embeddings: [...]}│
│  GET  /health     → {status:"ok", dim:1024}                │
└───────────────────────────┬───────────────────────────────┘
                            │ HTTP (httpx)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   API 进程(×4)        pipeline-worker      scripts/import_milvus
   HttpEmbeddingPort   HttpEmbeddingPort   HttpEmbeddingPort(可选)
```

- **服务端**：`app/application/embedding_server.py` 独立 FastAPI 应用，复用现有 `EmbeddingFactory` 加载本地 4.3G bge-m3（单进程，常驻）。
- **客户端**：`app/infrastructure/adapters/embedding_http.py` 实现 `EmbeddingPort`（`embed_query`/`embed_documents`），经 `httpx` 调远端（参考 `adapters/rerank.py` 同步模板 / `mineru.py` 异步模板）。
- **双模式开关**：`settings.embedding_mode: "remote" | "local"`——生产/正常用 remote（独立服务）；测试/无服务时用 local（保持现状 `EmbeddingFactory` 本地加载）。**默认 local**（不破坏现有单测与未起服务的开发环境），配好 `embedding_service_url` 后切 remote。

### 双模式设计理由
当前大量单测（`tests/test_ingest_graph.py`、`test_container.py` 等）与 `scripts/import_milvus.py` 依赖本地 `EmbeddingFactory`/fake。强制 remote 会破坏这些。双模式让迁移平滑：
- `container.get_embedder()` 根据 `settings.embedding_mode` 返回 **HttpEmbeddingPort**（remote）或 **EmbeddingFactory**（local），上层调用点（`index_document.embed_batch`、`search._get_embed_model`）**签名不变**。
- 测试仍走 local/fake，零改动。

---

## 三、服务端设计（`app/application/embedding_server.py`）

独立 FastAPI 应用（`embedding-service`）：

```python
# 伪代码骨架
app = FastAPI(title="embedding-service", version="0.1")
_factory = EmbeddingFactory()          # 复用现有加载路径（本地 bge-m3 优先）
_model = None                          # 懒加载：首个请求才加载模型

def _get_model():
    global _model
    if _model is None:
        _model = _factory.get_sentence_transformer()   # 或 get_hf_embeddings
    return _model

@app.get("/health")
async def health():
    return {"status": "ok", "dim": get_settings().embedding_dim}

@app.post("/embed")
def embed(req: EmbedRequest):   # {"text": "..."}
    vec = _get_model().encode(req.text, normalize_embeddings=True)[0]
    return {"embedding": vec.tolist()}

@app.post("/embed/batch")
def embed_batch(req: EmbedBatchRequest):   # {"texts": [...]}
    vecs = _get_model().encode(req.texts, normalize_embeddings=True)
    return {"embeddings": [v.tolist() for v in vecs]}
```

要点：
- **入口**：`python -m app.application.embedding_server`（或 `uv run uvicorn app.application.embedding_server:app --port 8084`）；pyproject 加脚本 `embedding-server`。
- **模型懒加载**：首个请求加载一次，此后常驻（彻底满足"不重复加载"）。
- **并发**：FastAPI 同步端点自动跑线程池（CPU 推理不阻塞事件循环）；bge-m3 CPU 编码单条数百 ms、整篇批量数秒，可接受。
- **超时**：客户端 `httpx.Timeout` 设宽松（批量数十秒级），参考 `mineru.py`。
- **维度**：`settings.embedding_dim`（1024），`normalize_embeddings=True` —— 与 Milvus schema / `EMBEDDING_DIM` 一致。

### 端口
建议 **8084**（避开 8000/8002/5171 约定端口）。

---

## 四、客户端设计（`app/infrastructure/adapters/embedding_http.py`）

```python
class HttpEmbeddingPort:   # 实现 domain/ports/embedding.py::EmbeddingPort
    def __init__(self, base_url: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
    def embed_query(self, text: str) -> list[float]:
        r = httpx.post(f"{self._base_url}/embed", json={"text": text}, timeout=self._timeout)
        r.raise_for_status()
        return r.json()["embedding"]
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(f"{self._base_url}/embed/batch", json={"texts": texts}, timeout=self._timeout)
        r.raise_for_status()
        return r.json()["embeddings"]
```

- 保持 **sync 签名**（`embed_query`/`embed_documents` 都是 sync）——上层调用点不变。
- 依赖已有 `httpx>=0.28.0`，无需新依赖。
- **异常**：网络/5xx 统一包装为 `EmbeddingServiceError`（归属 `MineruTransientError` 同类的可重试语义），供图节点 `retry_policy` 捕获。

---

## 五、接入改造点（签名不变，仅实现切换）

| 调用点 | 现状 | 改造 |
| --- | --- | --- |
| `app/infrastructure/container.py:317` | `get_hf_embeddings()` 预热（阻塞事件循环） | **删掉**；改调对 `embedding_service` 的 `/health` 探测（remote 模式）；local 模式保留预热或跳过 |
| `container.get_embedder()` | 返回 `EmbeddingFactory` | 按 `settings.embedding_mode` 返回 `HttpEmbeddingPort`（remote）或 `EmbeddingFactory`（local） |
| `index_document.py:82-88` `embed_batch` | `model.embed_documents([...])`（sync 在 async 节点内，阻塞 event loop） | 调用 `embed_documents`（远程则经 HTTP，天然非阻塞；本地则 `asyncio.to_thread` 包裹） |
| `search.py:179-182` `_get_embed_model` | `model.embed_query(...)`（sync，被 `chat.py` `asyncio.to_thread` 包裹） | 签名不变；远程即 HTTP，无需改 `chat.py` |
| `scripts/import_milvus.py:106` | `model.encode(...)`（本地 SentenceTransformer） | 可选：改走 `HttpEmbeddingPort.embed_documents`；或保留本地（离线导入脚本不强依赖服务） |
| `src/llm.py` `get_embedding_model`/`get_sentence_transformer` | 访问器 | 保留（local/兼容）；`EmbeddingFactory` 不删，作为 local 模式实现 |

**注意**：`index_document.embed_batch` 是 async 图节点，若走 `HttpEmbeddingPort`（sync httpx），会阻塞 event loop——需改为 `asyncio.to_thread` 包裹或提供 async 版本的端口方法。方案建议：`embed_batch` 节点对 remote 用 `asyncio.to_thread(embed_documents, ...)`（与现有 `search` 一致），对 local 同样 `to_thread`（把模型推理移出 event loop，属额外优化）。

---

## 六、配置（`app/infrastructure/settings.py`）

```python
# ── Embedding Service ─────────────────────────────
embedding_mode: str = "local"          # "local" 进程内加载（现状/测试）| "remote" 独立服务
embedding_service_url: str = "http://localhost:8084"
embedding_dim: int = 1024              # 已有，沿用
```

- 默认 `local`：无服务也能跑，单测/开发不破坏。
- 生产配 `EMBEDDING_MODE=remote` + `EMBEDDING_SERVICE_URL=http://embedding-service:8084`。

---

## 七、部署

### 7.1 独立进程（本地开发）
```bash
uv run uvicorn app.application.embedding_server:app --host 0.0.0.0 --port 8084
```

### 7.2 docker-compose 服务（`worker` 同款 profile）
```yaml
embedding-service:
  profiles: ["worker"]                 # 与 worker 同 profile，`--profile worker` 一起起
  build:
    context: .
  command: ["uv", "run", "uvicorn", "app.application.embedding_server:app", "--host", "0.0.0.0", "--port", "8084"]
  volumes:
    - ./models:/app/models             # 挂载本地 4.3G 模型（host 已有，避免镜像内复制）
  restart: unless-stopped
```
（镜像构建 / 健康检查在阶段 5 完善；此处给出可用骨架。）

### 7.3 启动顺序
`docker compose --profile worker up` 会拉起 `postgres/redis/minio/es/milvus` + `embedding-service` + `worker`。API 进程（`EMBEDDING_MODE=remote`）启动时对 `/health` 探测确认服务就绪。

---

## 八、测试

| 编号 | 测试 | 断言 |
| --- | --- | --- |
| E-1 | `test_embedding_http_client` | `HttpEmbeddingPort.embed_query`/`embed_documents` 构造正确的 HTTP 请求、解析响应（mock httpx） |
| E-2 | `test_embedding_server_health` | `/health` 返回 `{status:ok, dim:1024}` |
| E-3 | `test_embedding_server_embed` | `/embed` 单条 + `/embed/batch` 批量返回 1024 维归一化向量（mock 模型） |
| E-4 | `test_embedding_mode_switch` | `settings.embedding_mode` 切 remote 时 `get_embedder()` 返回 `HttpEmbeddingPort`；local 返回 `EmbeddingFactory` |
| E-5 | 迁移回归 | `index_document.embed_batch` / `search` 在两种模式下行为一致（对比维度/长度） |

现有单测（`test_ingest_graph.py`/`test_container.py`）默认 local/fake，不受影响。

---

## 九、风险与回滚

| 风险 | 规避 |
| --- | --- |
| 服务未起 → 检索/索引失败 | `embedding_mode=remote` 时 API 启动做 `/health` 探测；失败日志明确提示"先起 embedding-service" |
| remote HTTP 延迟（CN 网络内网） | 服务在同一 docker 网络/本机，ms 级；批量接口降低请求数 |
| 阻塞 event loop（sync httpx 在 async 节点） | `embed_batch` 用 `asyncio.to_thread` 包裹；或提供 async 端口方法 |
| 模型加载仍阻塞（服务端首个请求） | 服务端懒加载 + 启动预热（可选 `--preload`）；API/worker 已不加载 |
| 破坏单测 | 双模式默认 local；测试走 local/fake |
| **回滚** | 切回 `EMBEDDING_MODE=local` 即回滚（`EmbeddingFactory` 保留）；删除 `embedding_service` 服务即可 |

---

## 十、实施步骤

1. `app/application/embedding_server.py`：FastAPI 服务（`/health` `/embed` `/embed/batch`）。
2. `app/infrastructure/adapters/embedding_http.py`：`HttpEmbeddingPort`（`EmbeddingPort` 实现）。
3. `settings.py`：加 `embedding_mode` / `embedding_service_url`。
4. `container.get_embedder()`：按 mode 返回 remote/local；`start()` 预热改 `/health` 探测。
5. `index_document.embed_batch`：`asyncio.to_thread` 包裹（双模式通用）。
6. `pyproject`：`embedding-server` 脚本；`docker-compose`：`embedding-service` 服务。
7. 测试 E-1~E-5；文档回填本方案到 README / CLAUDE.md（启动排错记录）。
8. 手动验证：`EMBEDDING_MODE=remote` + 起服务 → 上传/检索/回答全链路；对比 `local` 一致。

---

## 十一、结论

**自写 FastAPI embedding 服务**是贴合现状的最优解：复用现有 4.3G 本地模型与 `EmbeddingFactory` 加载路径，零新镜像/零模型格式转换；双模式开关保证平滑迁移与测试不破坏。落地后 bge-m3 **只加载一次**（嵌入进程常驻），API/worker 不再重复加载与重复占内存（~11.5G → ~2.3G），启动显著变快。未来上 GPU 只需替换服务端推理内核。

> 附：若后续上 GPU，可评估换 **TEI（text-embeddings-inference）**——只需把模型转 safetensors、替换 `embedding_server` 为 TEI 容器，`HttpEmbeddingPort` 指向 TEI 的 `/v1/embeddings`，外部零改动。
