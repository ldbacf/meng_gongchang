# MedRAG — 项目开发规范

医疗领域 RAG 智能问答系统。FastAPI 后端（`backend/`）+ Vue3 前端（`frontend/`）。
技术栈：Python 3.12 / uv / SQLAlchemy(async) / LangGraph(重构中) / ES + Milvus 双路检索 / MinIO / DeepSeek / bge-m3。

---

## ⚠️ 红线（最重要）：禁止初始化数据

**绝对不要运行 `backend/cli/init_es.py` 或 `cli/init_milvus.py`**——它们会 **DROP 并重建** `chunks` 索引/集合，**清空已入库数据**（ES 索引与 Milvus 向量都是派生产物，重建后数据即丢）。

这两条命令**只允许在全新环境（无任何数据）**使用。判断方法：先查 `curl localhost:9200/chunks/_count` 与 Milvus `num_entities`，**非 0 就绝不能 init**。

### 数据恢复速查（若误删/缺失）
| 数据 | 恢复方式 |
| --- | --- |
| ES chunks | 从 MinIO `chunks` 桶下载 1248 个 JSON → `python -m cli.import_es --dir ./chunks`（快，无嵌入） |
| Milvus chunks | `python -m cli.init_milvus`（建空集合）→ `python -m cli.import_milvus --dir ./chunks --mode single`（CPU 重嵌入，**约 15h/1248 篇**，勿用 batch） |

数据主源在 MinIO：`parsed-data`(解析产物) / `chunks`(切分JSON) / `raw-docs`(原始PDF) / `doc-meta`(元数据)，**永远不要动这些**。

---

## 启动

1. 先启动 Docker Desktop，再 `cd backend && docker compose up -d`（8 个基础设施服务）。
2. DB schema 由 Alembic 管理（**已移除 lifespan create_all**）：
   - 全新库：`uv run alembic upgrade head`
   - 已有库：`uv run alembic stamp 0002_checkpoint`（标记基线，勿重复建表）
3. 后端 API（**必须用 `medrag-api`，不要直接 `uvicorn app.main:app`**）：
   ```bash
   cd backend && uv run medrag-api
   ```
   > **为什么**：checkpointer（AsyncPostgresSaver）经 psycopg async 连 PG，而 psycopg async
   > **不支持 Windows 的 ProactorEventLoop** → checkpointer 建不出来 → QAGraph 不可用
   > → **问答挂掉**（日志出现"警告: Postgres checkpointer 创建失败"）。
   >
   > **坑①（uvicorn ≥0.36 行为变更）**：光 `set_event_loop_policy(...)` **不够**。uvicorn 0.36
   > 起把 loop_factory 显式传给 `asyncio.run(..., loop_factory=...)`，而**传了 loop_factory 就
   > 绕过 event loop policy**；且 uvicorn 在 Windows 上把它硬编码为 `ProactorEventLoop`
   > （`uvicorn/loops/asyncio.py`）。所以 `app/run_api.py` 除了设
   > `WindowsSelectorEventLoopPolicy`，还给 uvicorn 传 **`loop="none"`**（→ loop_factory=None
   > → 回落到 policy）。**勿加 `--workers`/`--reload`**（子进程路径不同）；多进程请用
   > compose 的 `backend` 服务（Linux 镜像无此限制）。
   >
   > **坑②（`localhost` 会静默挂住）**：`.env` 里 **`POSTGRES_HOST` 必须是 `127.0.0.1`，不能写
   > `localhost`**。这台 Windows 上 `localhost` 会让 psycopg async 的 `connect()` **静默卡死**
   > （不报错、不超时），表现为服务停在"embedding-service 就绪"之后、再无输出。
   > asyncpg（SQLAlchemy engine）容忍 `localhost`，所以只有 checkpointer 这一步受影响。
   > `REDIS_HOST` / `MINIO_ENDPOINT` 同样是 `127.0.0.1`（同一个坑，早先已修）。
4. 入库 worker（独立终端，消费队列）：
   ```bash
   cd backend && uv run pipeline-worker
   ```
5. embedding 服务（可选但推荐，模型只加载一次；.env 设 `EMBEDDING_MODE=remote`）：
   ```bash
   cd backend && uv run embedding-server      # 8084
   ```
6. 前端：`cd frontend && npm run dev`（端口 **5171**，勿用 5173——在 Windows 保留端口段内无法绑定）

**Docker 全量起**：`cd backend && docker compose --profile app up -d --build`（含 backend/ingestion-worker/embedding-service）

**端口约定**：后端 8000；Attu 8002（勿占用 8000）；embedding 8084；前端 5171。
**入口**：`medrag-api`（API）/ `pipeline-worker`（worker）/ `embedding-server`（嵌入服务）/ `medrag-*`（运维 CLI，见 `cli/`）。

---

## 开发规范

### 架构分层（已落地：`src/` 已并入 `app/`）
`interface → application → domain ← infrastructure`，依赖严格单向；**唯一应用包 = `app/`**：

```
app/
├── main.py  run_api.py        入口（FastAPI 装配 / 启动）
├── interface/                 deps · sse · schemas · security · routers/
├── application/               graphs/(ingest+rag) · services/ · rag/
├── domain/                    chunking · document · rag · retrieval · ports（纯函数，零外部依赖）
└── infrastructure/            adapters/ · db/(models+session) · es/ · milvus/ · redis/ ·
                               checkpoint/ · observability/ · search.py · indexer.py · ws_manager.py · key_manager.py
```
- `domain/` 纯函数、零外部依赖（仅 stdlib）；承载状态机/契约/算法
- `infrastructure/` 实现端口适配器；客户端经 `AppContainer` 注入（**禁止模块级全局单例**）
- 契约冻结见 `docs/langgraph-refactor/总需求文档.md` §7（pipeline_steps / SSE v1 / doc_id 口径 / TaskStatus 状态机）

### 配置
- 配置单一真相源：`backend/app/infrastructure/settings.py`（pydantic-settings），**不要**在别处 `os.getenv`
- 回答模型 = `deepseek-v4-flash`（.env 与 settings 默认值一致）

### 测试
- `cd backend && uv run pytest`（150 个单测；契约/状态机/鉴权/图/观测/CLI）
- 手动脚本在 `backend/manual/`（**注意不是 `tests/`**），依赖真实 API key；**控制台乱码时加** `PYTHONIOENCODING=utf-8`

### 其它
- 依赖用 `uv add` / `uv sync`，锁定在 `uv.lock`
- 后端代码改动后 `uv run python -c "import app.main"` 做导入体检
- Windows 下 curl 发中文 JSON 会因 GBK 编码解析失败：用 UTF-8 文件 + `--data-binary @file`

---

## 关键文档
- 重构方案总纲：`docs/langgraph-refactor/总需求文档.md`（阶段 0~5 文档同目录）
- 启动排错记录：`docs/error_ok/`
