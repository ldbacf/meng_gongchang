# MedRAG — 医疗领域 RAG 智能问答系统

> **Medical Retrieval-Augmented Generation Assistant** — 基于 PDF 文档解析、双路检索引擎与 LLM 的医疗文献问答助手。

面向基层医疗场景的 RAG 智能问答系统，实现从 PDF 上传、解析、切分、向量化存储到智能检索与 LLM 回答的完整管线。

```
上传 PDF → MinerU 解析 → 三粒度切分 (L0/L1/L2) → ES BM25 + Milvus 向量双路索引
                                                          ↓
用户 Query → DeepSeek 意图识别 → 双路召回 → RRF 融合 → Reranker 精排 → LLM 回答
```

## 🧩 技术栈

| 层次       | 技术                                                                               |
| ---------- | ---------------------------------------------------------------------------------- |
| **前端**   | Vue 3 + TypeScript + Vite + Pinia + Vue Router + Tailwind CSS                      |
| **后端**   | Python 3.12 + FastAPI + SQLAlchemy (async) + LangChain                              |
| **数据库** | PostgreSQL (业务) + Redis (队列) + Elasticsearch (BM25) + Milvus (向量)            |
| **存储**   | MinIO (原始 PDF / 元信息 / 解析产物 / 切分结果)                                    |
| **外部API**| DeepSeek (意图识别 + 回答) · SiliconFlow (Reranker) · MinerU (PDF 解析)            |
| **向量**   | BGE-M3 (1024 维, COSINE)                                                           |
| **容器**   | Docker Compose（8 个基础设施服务）                                                  |

## 🚀 快速开始

前置条件：Python ≥ 3.12、Node.js ≥ 18、Docker & Docker Compose。

### 一键启动（推荐）

```powershell
# 基础设施 + 3 个后端进程 + 前端，各占一个窗口，日志实时可见
.\scripts\dev.ps1

.\scripts\dev.ps1 -NoDocker     # 基础设施已在跑
.\scripts\dev.ps1 -NoFrontend   # 只起后端
.\scripts\dev.ps1 -NoReload     # 关掉热重载

.\scripts\dev-stop.ps1          # 停止（-IncludeDocker 连基础设施一起停）
```

### 热重载

默认开启，改 `backend/app/**` 下代码自动重启：

| 进程 | 方式 | 说明 |
|---|---|---|
| API | `--reload` | uvicorn 走子进程重载；该路径下 uvicorn 正好返回 `SelectorEventLoop`，psycopg async 仍可用 |
| worker | `--reload` | watchfiles **重启整个进程**（不是热替换模块），避免残留半截队列状态 |
| embedding | 无 | bge-m3 加载约 30s，重载得不偿失；改相关代码手动重启 |

> 手动等价：`uv run medrag-api --reload` / `uv run pipeline-worker --reload`

### 手动启动：共 4 个进程

| 服务 | 命令 | 端口 | 为什么需要独立进程 |
|---|---|---|---|
| 基础设施 | `docker compose up -d`（`backend/`） | 5432 / 6379 / 9000 / 9200 / 19530 | PostgreSQL、Redis、MinIO、ES、Milvus |
| **API** | `uv run medrag-api` | 8000 | 只做 HTTP + SSE，必须随时可响应 |
| **Embedding** | `uv run embedding-server` | 8084 | bge-m3 常驻，模型只加载一次；API 与 worker 共用，重启 API 不用重载模型（约 30s） |
| **Worker** | `uv run pipeline-worker` | — | 消费 Redis Stream，跑 MinerU 解析 + 切分 + 向量化 + 写库；单个 PDF 可达数分钟，**不能放在请求链路里** |
| 前端 | `npm run dev` | 5171 | Vite 开发服务器（仅开发期需要） |

```bash
cd backend && docker compose up -d
cp .env.example .env          # DEEPSEEK_API_KEY / SILICONFLOW_API_KEY / MINERU_TOKENS
uv sync
uv run medrag-init-es && uv run medrag-init-milvus    # 仅首次（会重建索引，别重复跑）
```

> 前端固定 **5171**：5173 落在 Windows 保留端口段无法绑定；后端 CORS 默认按 5171 配置。

### 日志

三个后端进程共用同一套 JSON 日志（每行一个 JSON 对象）：

```json
{"level":"INFO","ts":"...","msg":"请求","logger":"app.access",
 "ctx":{"method":"GET","path":"/api/v1/conversations","status":200,"ms":42.1}}
```

- 默认 `INFO`：只打业务日志与请求日志，`/health` `/metrics` 等探针**静默**（否则会刷屏）
- `LOG_LEVEL=debug`：连探针与第三方库细节一起打
- 慢请求（>3s）与 5xx 自动升级为 `WARNING`，异常带完整 traceback
- uvicorn 自带的访问日志已关闭（信息量只有状态码），由 [app/interface/middleware.py](backend/app/interface/middleware.py) 取代

> 详细安装步骤见 [backend/README.md](backend/README.md) 与 [frontend/README.md](frontend/README.md)。

## 📄 文档处理与检索流程

| 步骤 | 命令 |
| ---- | ---- |
| 批量提交 PDF 解析 | `uv run python scripts/scan_submit.py` + 启动 Worker |
| 三粒度切分 | `uv run python scripts/run_chunker.py --upload --out-dir ./chunks` |
| 导入 ES / Milvus | `uv run python scripts/import_es.py --dir ./chunks`；`import_milvus.py` |
| 检索 + 回答 | Python SDK：`from src.search import search, search_and_answer` |

### 检索管线

```
query → 意图识别 (DeepSeek V4 Flash)
      → Milvus 向量召回 + ES BM25 召回 (各 topK=200)
      → RRF 融合 → Qwen3-Reranker-4B 精排
      → DeepSeek V4 Pro 回答 (流式/非流式，引用标注 [N])
```

### 文档状态机

```
pending → processing → parsed → chunked → (ES + Milvus)
                    ↘ failed → (重试时重置为 pending)
```

## 🖥️ 前端功能

对话界面（SSE 流式）、文献引用卡片、内嵌 PDF 预览、JWT 认证、用户管理、响应式布局。

## 📁 目录结构

```
medrag/
├── backend/     # Python 后端（FastAPI + 文档处理管线 + RAG 检索）
├── frontend/    # Vue 3 前端（对话界面）
└── README.md
```

## 📄 开源许可

MIT License
