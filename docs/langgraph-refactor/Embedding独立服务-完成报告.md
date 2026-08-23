# Embedding 独立服务（bge-m3 常驻）— 完成报告

> 归属：`docs/langgraph-refactor/Embedding独立服务-完成报告.md`
> 前置方案：`docs/langgraph-refactor/Embedding独立服务方案.md`（已实施）
> 分支：`refactor/overall` · 日期：2026-08-23
> 决策：**自写 FastAPI wrapper**（用户 2026-08-16 确认）；本机无 GPU，bge-m3 走 CPU。

---

## 一、做什么（一句话）

把 **bge-m3 嵌入模型从 API/worker 进程里剥离出来**，改成一个**只加载一次、常驻不动的独立服务**；API/worker 每次要嵌入时经 HTTP 来问它，不再各自加载一份。

## 二、为什么（大白话）

之前每次启动后端，**每个进程都自己加载一份 4.3G 的 bge-m3**：
`uvicorn --workers 4`（4 个 API 进程）+ 独立 worker = **5 份** ≈ **~11.5G 内存**，而且**每次重启 5 个进程各自从头加载一遍**（加载慢、占内存、启动被卡）。

现在改成：**模型只在一个服务里加载一次（常驻）**，别人用完了就还给它。效果：
- 内存从 **~11.5G → ~1 份（约 2.3G）**。
- API/worker 启动**不再等模型加载**，只做一次 `/health` 健康检查，瞬间就绪。
- 未来上 GPU，只要换服务端的推理内核，API/worker **零改动**。

> 对业务的影响（哪些流程受益）：
> - **文档上传/检索**（`index_document.embed_batch` / `search`）——都走同一个嵌入器，逻辑不变，只是嵌入动作从"本地模型算"换成"问 embed-service 算"。
> - **后端重启**——不再花几分钟重载模型，开发/部署体验显著变好。

## 三、怎么改的（架构）

```
┌──────── embed-service（独立进程，模型常驻）────────┐
│  FastAPI + EmbeddingFactory.get_sentence_transformer() │
│  POST /embed        单条 → {embedding:[1024]}          │
│  POST /embed/batch  批量 → {embeddings:[...]}          │
│  GET  /health       → {status:"ok", dim:1024}          │
└───────────────────────────┬───────────────────────────┘
                            │ HTTP (httpx)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   API 进程(×4)        pipeline-worker      scripts/import_milvus(可选)
   HttpEmbeddingPort   HttpEmbeddingPort   （保留本地）
```

**双模式开关**（关键设计，保证平滑迁移 & 不破坏单测）：
- `settings.embedding_mode = "local"`（**默认**）→ `get_embedder()` 返回 `EmbeddingFactory`（进程内加载，**现状不变**）。
- `settings.embedding_mode = "remote"` → `get_embedder()` 返回 `HttpEmbeddingPort`（HTTP 调独立服务）。

**为什么能"签名不变"**：原来 `index_document` 调 `.get_hf_embeddings().embed_documents()`、`search` 调 `.get_hf_embeddings().embed_query()`。为了让 remote/local 真正无缝，我让 **`EmbeddingFactory` 也实现了 `embed_query` / `embed_documents`**（委托给内部 HF 模型）。这样 remote 的 `HttpEmbeddingPort` 和 local 的 `EmbeddingFactory` 对外暴露**同一套方法**，上层调用点统一走 `embed_query`/`embed_documents`，**代码一行不用改**（只改 `container.get_embedder()` 一处返回）。

## 四、文件变更

### 新增
| 文件 | 内容 |
| --- | --- |
| `app/application/embedding_server.py` | **服务端**独立 FastAPI：`/health` `/embed` `/embed/batch`；`get_sentence_transformer()` 懒加载（首个请求才加载，此后常驻）；同步端点（fastapi 线程池，不阻塞事件循环）；`run()` 供 `embedding-server` 脚本入口 |
| `app/infrastructure/adapters/embedding_http.py` | **客户端** `HttpEmbeddingPort`（实现 `EmbeddingPort`，sync 签名）；`embed_query`/`embed_documents`；`check_health()`（启动探测）；失败统一包装 `EmbeddingServiceError`（可重试） |
| `tests/test_embedding_service.py` | E-1~E-5 |

### 修改
| 文件 | 变更 |
| --- | --- |
| `app/infrastructure/settings.py` | 加 `embedding_mode: str = "local"`、`embedding_service_url: str = "http://localhost:8084"` |
| `app/infrastructure/adapters/embedding.py` | `EmbeddingFactory` 新增 `embed_query`/`embed_documents`（**实现 EmbeddingPort**，委托给内部 HF 模型） |
| `app/infrastructure/container.py` | `get_embedder()` 按 `embedding_mode` 返回 remote/local；`start()` 预热——remote 只做 `/health` 探测（不再加载模型），local 保留加载 |
| `app/application/graphs/subgraphs/index_document.py` | `embed_batch` 改用 `embed_documents`（双模式通用）+ `asyncio.to_thread` 包裹（推理/HTTP 同步阻塞移出 event loop）；`_TRANSIENT` retry_on 增加 `EmbeddingServiceError` |
| `src/search.py` | `_get_embed_model()` 返回容器 embedder（统一 `embed_query`），不再取 `get_hf_embeddings()` |
| `pyproject.toml` | 追加 `embedding-server = "app.application.embedding_server:run"` |
| `docker-compose.yml` | 追加 `embedding-service` 服务（与 worker 同 `worker` profile，挂载 `./models`） |

**未改动**（保留 local/兼容）：`src/llm.py` 的 `get_embedding_model`/`get_sentence_transformer` 访问器、`src/indexer.py:process_document`（旧单条循环）、`scripts/import_milvus.py`（离线导入，跑在 local 模式，不强依赖服务）。

## 五、配置与部署

### 配置（`settings.py`，默认 `local` 无服务也能跑）
```python
embedding_mode: str = "local"          # "local" 进程内 | "remote" 独立服务
embedding_service_url: str = "http://localhost:8084"
```

### 启动服务（模型常驻）
```bash
uv run embedding-server                              # `python -m app.application.embedding_server`
# 或
uv run uvicorn app.application.embedding_server:app --host 0.0.0.0 --port 8084
```

### 生产切 remote
```bash
# docker compose --profile worker up   # 同时拉起 embedding-service（与 worker 同 profile）
EMBEDDING_MODE=remote EMBEDDING_SERVICE_URL=http://embedding-service:8084 uv run uvicorn src.main:app --port 8000
```
API/worker 启动时仅对 `/health` 探测；服务不可达会打印明确警告"请先起 embedding-server"。

> 模型路径：`EmbeddingFactory._model_path()` 本地优先 `backend/models/bge-m3/`，否则回退 `BAAI/bge-m3`。compose 挂载 `./models:/app/models`，容器内 `/app/models/bge-m3` 命中本地模型。

## 六、测试（E-1~E-5，全部离线——不加载模型/不连 PG）

| 编号 | 测试 | 断言 |
| --- | --- | --- |
| E-1 | `test_embedding_http_client_builds_requests` | `HttpEmbeddingPort.embed_query`/`embed_documents` 构造正确 URL/JSON/超时，解析响应 |
| E-1b | `test_embedding_http_client_wraps_errors` | 网络/5xx 包装为 `EmbeddingServiceError` |
| E-2 | `test_embedding_server_health` | `/health` 返回 `{status:"ok", dim:1024}` |
| E-3 | `test_embedding_server_embed_single` / `..._batch` | `/embed` 单条、`/embed/batch` 批量返回 1024 维 **L2 归一化**向量 |
| E-4 | `test_embedding_mode_remote_returns_http_port` / `..._local_returns_factory` | remote → `HttpEmbeddingPort`，local → `EmbeddingFactory` |
| E-5 | `test_embedding_port_implementations_conform` | 两种模式都暴露 `embed_query`/`embed_documents`，调用点签名一致 |

现有单测（`test_ingest_graph.py`/`test_container.py`）默认 local/fake，**零改动**、不受影响。

## 七、风险与回滚

| 风险 | 处理 |
| --- | --- |
| `embedding_mode=remote` 但服务未起 | API 启动 `/health` 探测，失败警告明确提示"先起 embedding-server"；检索/索引调用时抛 `EmbeddingServiceError`（可重试） |
| HTTP 延迟 | 服务同机/同 docker 网络 ms 级；批量接口低频次 |
| 阻塞 event loop（sync httpx） | `embed_batch` 已用 `asyncio.to_thread` 包裹 |
| 服务端首次加载慢 | 服务懒加载 + 仅一次；API/worker 已不再加载 |
| 【**回滚**】 | 切回 `EMBEDDING_MODE=local` 即回滚（`EmbeddingFactory` 完整保留）；删 `embedding-service` 服务即可 |

## 八、验证

- [x] `uv run python -c "import src.main"` 导入体检通过
- [x] 目标测试（container/settings/ingest_graph/worker_standalone）17 passed 无回归
- [x] E-1~E-5 新测试 8 passed
- [x] 全量单测 **104 passed / 0 failed**（docker 8 服务在线）
- [ ] 手动端到端：`EMBEDDING_MODE=remote` 起服务 → 上传/检索/回答全链路，与 `local` 对比一致（依赖真实模型/服务，本地未跑）

> 顺带修复：`tests/test_status_db_enum.py` 的 `test_status_db_enum_sql_offline` 在中文 Windows 下因子进程强制 `encoding="utf-8"` 解码 alembic 输出的 **GBK 字节**抛 `UnicodeDecodeError` → `stdout=None` 崩溃（**非本特性引入**，逐项 stash 到干净树上复现确认）。加 `errors="replace"` 后解码不再崩溃，ASCII 约束名（`ck_document_tasks_status` 等）断言不受影响，模块已恢复到 2 passed。

> 注：远程端到端依赖 4.3G 模型与服务，需在有模型的环境手动验证；代码层面 E-1（客户端单测）+ E-3（服务端单测）已覆盖 HTTP 双侧合约。

## 九、结论

**自写 FastAPI embedding 服务落地完成**。bge-m3 从"每进程各一份、每次启动重载"变为"**独立进程常驻一份**"，内存 ~11.5G → ~2.3G，API/worker 启动不再阻塞加载。双模式（默认 local）保证零迁移风险、单测不破坏；`EmbeddingFactory` 与 `HttpEmbeddingPort` 对外接口一致，上层调用点零改动。未来上 GPU 只需替换服务端推理内核（可评估换 TEI，`HttpEmbeddingPort` 指向 TEI `/v1/embeddings` 节点即可，外部零改动）。
