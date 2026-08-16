# MedRAG — 项目开发规范

医疗领域 RAG 智能问答系统。FastAPI 后端（`backend/`）+ Vue3 前端（`frontend/`）。
技术栈：Python 3.12 / uv / SQLAlchemy(async) / LangGraph(重构中) / ES + Milvus 双路检索 / MinIO / DeepSeek / bge-m3。

---

## ⚠️ 红线（最重要）：禁止初始化数据

**绝对不要运行 `backend/scripts/init_es.py` 或 `init_milvus.py`**——它们会 **DROP 并重建** `chunks` 索引/集合，**清空已入库数据**（ES 索引与 Milvus 向量都是派生产物，重建后数据即丢）。

这两个脚本**只允许在全新环境（无任何数据）**使用。判断方法：先查 `curl localhost:9200/chunks/_count` 与 Milvus `num_entities`，**非 0 就绝不能 init**。

### 数据恢复速查（若误删/缺失）
| 数据 | 恢复方式 |
| --- | --- |
| ES chunks | 从 MinIO `chunks` 桶下载 1248 个 JSON → `import_es.py --dir ./chunks`（快，无嵌入） |
| Milvus chunks | `init_milvus.py`（建空集合）→ `import_milvus.py --dir ./chunks --mode single`（CPU 重嵌入，**约 15h/1248 篇**，勿用 batch） |

数据主源在 MinIO：`parsed-data`(解析产物) / `chunks`(切分JSON) / `raw-docs`(原始PDF) / `doc-meta`(元数据)，**永远不要动这些**。

---

## 启动

1. 先启动 Docker Desktop，再 `cd backend && docker compose up -d`（8 个基础设施服务）。
2. DB schema 由 Alembic 管理（**已移除 lifespan create_all**）：
   - 全新库：`uv run alembic upgrade head`
   - 已有库：`uv run alembic stamp 0002_checkpoint`（标记基线，勿重复建表）
3. 后端：`cd backend && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000`
4. 前端：`cd frontend && npm run dev`（端口 **5171**，勿用 5173——在 Windows 保留端口段内无法绑定）

**端口约定**：后端 8000；Attu 8002（勿占用 8000）；前端 5171。

---

## 开发规范

### 架构分层（重构目标）
`interface → application → domain ← infrastructure`，依赖严格单向：
- `domain/` 纯函数、零外部依赖（仅 stdlib）；承载状态机/契约/算法
- `infrastructure/` 实现端口适配器；客户端经 `AppContainer` 注入（**禁止模块级全局单例**）
- 契约冻结见 `docs/langgraph-refactor/总需求文档.md` §7（pipeline_steps / SSE v1 / doc_id 口径 / TaskStatus 状态机）

### 配置
- 配置单一真相源：`backend/app/infrastructure/settings.py`（pydantic-settings），**不要**在别处 `os.getenv`
- 回答模型 = `deepseek-v4-flash`（.env 与 settings 默认值一致）

### 测试
- `cd backend && uv run pytest`（26 个单测，96% 覆盖；契约/状态机/鉴权）
- 手动脚本在 `backend/test/`，依赖真实 API key；**控制台乱码时加** `PYTHONIOENCODING=utf-8`

### 其它
- 依赖用 `uv add` / `uv sync`，锁定在 `uv.lock`
- 后端代码改动后 `uv run python -c "import src.main"` 做导入体检
- Windows 下 curl 发中文 JSON 会因 GBK 编码解析失败：用 UTF-8 文件 + `--data-binary @file`

---

## 关键文档
- 重构方案总纲：`docs/langgraph-refactor/总需求文档.md`（阶段 0~5 文档同目录）
- 启动排错记录：`docs/error_ok/`
