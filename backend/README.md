# MedRAG Backend — PDF 文档解析与 RAG 检索后端

> 基于 FastAPI 的医疗文档智能处理与 RAG 问答服务。

## 📋 功能概述

- **PDF 解析** — 对接 MinerU API v4，解析为 Markdown + 图片
- **三粒度切分** — L0（论文元信息）/ L1（段落）/ L2（表格）
- **双路索引** — Elasticsearch BM25 + Milvus 向量检索
- **意图识别** — DeepSeek V4 Flash 分析 Query 领域与覆盖度
- **检索融合** — RRF 融合 + Qwen3-Reranker-4B 精排
- **LLM 回答** — DeepSeek V4 Pro 流式/非流式生成，带文献引用
- **后台 Worker** — 异步轮询 MinerU 解析结果
- **JWT 认证** — 用户登录与 Token 刷新

## 🧰 技术栈

| 组件     | 技术                                                        |
| -------- | ----------------------------------------------------------- |
| 框架     | FastAPI + Uvicorn + Python 3.12+                            |
| 包管理   | uv                                                          |
| ORM      | SQLAlchemy (async) + asyncpg                                |
| 存储     | Redis (队列) · MinIO (4 桶) · ES 8.19+IK · Milvus 2.4+BGE-M3 |
| LLM      | LangChain (ChatOpenAI / HuggingFaceEmbeddings)              |
| 外部 API | DeepSeek · 硅基流动 · MinerU                                |

## 🚀 快速开始

前置条件：Python ≥ 3.10（推荐 3.12）、Docker & Docker Compose。

### 1. 配置环境变量

```bash
cp .env.example .env
```

必填：`JWT_SECRET_KEY`。选填（按需）：`DEEPSEEK_API_KEY`（意图识别 + 回答）、`SILICONFLOW_API_KEY`（Reranker 精排）、`MINERU_TOKENS`（PDF 解析，多 Token 逗号分隔，自动轮询切换）。

### 2. 启动基础设施（8 个服务）

```bash
docker compose up -d
```

| 服务          | 端口                          | 用途               |
| ------------- | ----------------------------- | ------------------ |
| PostgreSQL    | 5432                          | 业务数据           |
| Redis         | 6379                          | 任务队列           |
| MinIO         | 9000 (API) / 9001 (Console)   | 对象存储           |
| Elasticsearch | 9200                          | BM25 全文检索      |
| Kibana        | 5601                          | ES 可视化          |
| Milvus        | 19530 (gRPC)                  | 向量检索           |
| etcd          | 2379                          | Milvus 元数据      |
| Attu          | 8000 (GUI)                    | Milvus 管理面板    |

### 3. 安装依赖并初始化索引（★ 必做）

```bash
conda activate rag_test   # 或自建环境
uv sync
uv run python scripts/init_es.py       # 创建 ES 索引（ik_smart 分词）
uv run python scripts/init_milvus.py   # 创建 Milvus Collection
```

### 4. （可选）回填预置文献

接手已有数据（ES / MinIO 已有 chunks）时，将记录同步到 `document_tasks` 表，使其在管理界面可见并支持删除：

```bash
uv run python scripts/backfill_document_tasks.py
```

### 5. 启动 API

```bash
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
# 生产：uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

API 文档：http://localhost:8000/docs

> 注册账号后默认 `enabled=false`，需管理员在数据库中改为 `admin` + `enabled=true` 后才能登录。

## 📄 PDF 文档处理流程

```bash
# 1. 批量提交 PDF（放入 after/ 目录）到 MinerU
uv run python scripts/scan_submit.py

# 2. 启动 Worker 轮询解析结果（pending → processing → parsed）
uv run python -c "from src.worker import run_worker; run_worker()"

# 3. 三粒度切分并上传 MinIO（支持断点续跑/失败隔离）
uv run python scripts/run_chunker.py --upload --out-dir ./chunks

# 4. 导入索引
uv run python scripts/import_es.py --dir ./chunks
uv run python scripts/import_milvus.py --dir ./chunks --mode batch --device cuda:0
```

> `--device cuda:0` 使用 GPU 编码，不加则使用 CPU。

## 🔍 检索管线

```
query → 意图识别 (DeepSeek V4 Flash) → 领域分类 / 覆盖度 / 重写
      → Milvus 向量召回 + ES BM25 召回 (各 topK=200)
      → RRF 融合 (score = 1/(60+rank_m) + 1/(60+rank_e))
      → Qwen3-Reranker-4B 精排 (硅基流动 API)
      → DeepSeek V4 Pro 回答 (仅基于文献作答，引用 [N])
```

### Python SDK 调用

```python
from src.search import search, search_with_intent, search_and_answer

hits = search("高血压的药物选择", filters={"level": "L1"}, top_k=20)  # 纯检索
hits, intent = search_with_intent("儿童发热怎么用药", top_k=20)         # + 意图识别
result = search_and_answer("高血压的药物选择", top_k=10)                # + Rerank + 回答
stream = search_and_answer("高血压的药物选择", stream=True)             # 流式回答
```

## 🧪 测试

```bash
uv run python test/test_query_intent.py          # 意图识别
uv run python test/test_siliconflow_rerank.py    # Reranker
uv run python test/test_llm_answer.py            # LLM 回答（sync/stream/pipeline）
uv run python test/test_embedding_compat.py      # 向量编码一致性
uv run python test/test_mineru.py                # MinerU API
```

## 📝 开发说明

- 依赖用 `uv sync` 管理（`uv add <package>` 添加），锁定在 `uv.lock`
- 基础设施数据持久化在 `data/`，BGE-M3 模型下载到 `models/`（均 gitignore）
- 完整配置项见 `.env.example`，关键分组：数据库连接、MinIO 四桶、MinerU 解析参数
- ES 需提前下载 IK 分词器插件包到 `data/plugins/`，否则 ES 启动失败

## ❗ 常见问题

- **ES 启动失败** — 确认 IK 插件包已放到 `data/plugins/`
- **Milvus 启动慢** — 首次需下载镜像并建索引，等待 1-2 分钟
- **uv sync 失败** — 确认 conda 环境已激活，Python ≥ 3.10
