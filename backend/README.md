# MedRAG Backend — PDF 文档解析与 RAG 检索后端

> 基于 FastAPI 的医疗文档智能处理与 RAG 问答服务。

---

## 📋 功能概述

后端提供完整的 PDF 文档处理管线与 RAG 检索问答能力：

- **PDF 解析** — 对接 MinerU API v4，将 PDF 解析为 Markdown + 图片
- **三粒度切分** — 将文献切分为 L0（论文元信息）/ L1（段落）/ L2（表格）
- **双路索引** — Elasticsearch BM25 全文检索 + Milvus 向量检索
- **意图识别** — DeepSeek V4 Flash 分析用户 Query 的领域与覆盖度
- **检索融合** — RRF 融合 + Qwen3-Reranker-4B 精排
- **LLM 回答** — DeepSeek V4 Pro 流式/非流式回答生成，带文献引用
- **后台 Worker** — 异步轮询 MinerU 解析结果
- **JWT 认证** — 用户登录与 Token 刷新

---

## 🧰 技术栈

| 组件         | 技术                                                    |
| ------------ | ------------------------------------------------------- |
| 框架         | FastAPI + Uvicorn                                       |
| 语言         | Python 3.12+                                            |
| 包管理       | uv                                                      |
| ORM          | SQLAlchemy (async) + asyncpg                            |
| 任务队列     | Redis (list)                                            |
| 对象存储     | MinIO (4 桶)                                            |
| 全文检索     | Elasticsearch 8.19 + IK 分词器                          |
| 向量检索     | Milvus 2.4 + BGE-M3 (1024维, COSINE)                   |
| LLM 框架     | LangChain (ChatOpenAI / HuggingFaceEmbeddings)          |
| 外部 API     | DeepSeek · 硅基流动 · MinerU                           |

---

## 📁 目录结构

```
backend/
├── src/                          # 核心源码
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 全局配置（PG/Redis/MinIO/ES/Milvus/API）
│   ├── auth.py                   # JWT 认证中间件
│   ├── db.py                     # SQLAlchemy 异步引擎
│   ├── models.py                 # ORM 模型
│   ├── schemas.py                # Pydantic 数据模型
│   ├── key_manager.py            # MinerU 多 Token 轮询与额度管理
│   ├── redis_client.py           # Redis 队列操作封装
│   ├── minio_client.py           # MinIO 四桶操作封装
│   ├── mineru_client.py          # MinerU API v4 客户端（提交/查询）
│   ├── chunker.py                # 三粒度分层切分（L0/L1/L2）
│   ├── search.py                 # 双路检索 + RRF + Rerank + search_and_answer
│   ├── query_intent.py           # DeepSeek 意图识别
│   ├── reranker.py               # 硅基流动 Reranker (LangChain BaseDocumentCompressor)
│   ├── llm.py                    # 模型工厂（get_chat_model / get_embedding_model）
│   ├── llm_answer.py             # LLM 回答生成（流式 SSE / 非流式）
│   ├── worker.py                 # 后台 Worker（轮询 MinerU 结果）
│   └── routers/                  # API 路由
├── scripts/                      # 数据处理脚本
│   ├── scan_submit.py            # 文件夹扫描 → MinerU 批量提交
│   ├── run_chunker.py            # 批量切分（断点续跑/失败隔离/原子写入）
│   ├── backfill_document_tasks.py# 从 ES + MinIO 回填 document_tasks（预置文献）
│   ├── download_model.py         # 下载 BGE-M3 模型
│   ├── init_es.py                # ES 索引初始化（IK 分词器映射）
│   ├── init_milvus.py            # Milvus Collection 初始化
│   ├── import_es.py              # 批量导入 chunks → ES
│   └── import_milvus.py          # 批量导入 chunks → Milvus
├── test/                         # 测试
│   ├── test_query_intent.py      # 意图识别（8 cases）
│   ├── test_siliconflow_rerank.py# Reranker API + 链路测试
│   ├── test_llm_answer.py        # LLM 回答（sync/stream/pipeline）
│   ├── test_embedding_compat.py  # 向量编码一致性验证
│   ├── test_mineru.py            # MinerU API 测试
│   ├── test_mineru_keys.py       # MinerU 多 Key 测试
│   └── test_pipeline.py          # 整体管线测试
├── docker-compose.yml            # 基础设施容器编排（8 个服务）
├── pyproject.toml                # 项目元数据与依赖
├── .env.example                  # 环境变量模板
├── .gitignore
├── CLAUDE.md                     # Claude Code 上下文
└── README.md                     # 本文件
```

---

## 🚀 快速开始

### 前置条件

- Python ≥ 3.10（推荐 3.12）
- Docker & Docker Compose
- CUDA 设备（可选，用于 BGE-M3 编码）

### 1. 启动基础设施

```bash
docker compose up -d
```

这会启动 8 个服务：

| 服务          | 镜像                            | 端口                          | 用途                      |
| ------------- | ------------------------------- | ----------------------------- | ------------------------- |
| PostgreSQL    | postgres:16-alpine              | 5432                          | 业务数据存储              |
| Redis         | redis:7.4.8                     | 6379                          | Worker 任务队列           |
| MinIO         | cgr.dev/chainguard/minio:latest | 9000 (API) / 9001 (Console)  | PDF & 解析产物对象存储    |
| Elasticsearch | elasticsearch:8.19.15           | 9200 (REST) / 9300 (Transport)| BM25 全文检索             |
| Kibana        | kibana:8.19.15                  | 5601                          | ES 可视化                 |
| Milvus        | milvusdb/milvus:v2.4.15         | 19530 (gRPC)                  | 向量检索                  |
| etcd          | quay.io/coreos/etcd:v3.5.5      | 2379                          | Milvus 元数据             |
| Attu          | zilliz/attu:v2.4.12             | 8000                          | Milvus 管理面板           |

检查服务健康状态：

```bash
# ES
curl http://localhost:9200/_cluster/health

# Attu 面板
open http://localhost:8000

# Kibana
open http://localhost:5601
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入必要的 API Key：

```ini
# ── DeepSeek（意图识别 + LLM 回答）──
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_INTENT_MODEL=deepseek-v4-flash
DEEPSEEK_ANSWER_MODEL=deepseek-v4-pro

# ── 硅基流动（Reranker）──
SILICONFLOW_API_KEY=sk-your-key-here
SILICONFLOW_RERANK_MODEL=Qwen/Qwen3-Reranker-4B

# ── MinerU（PDF 解析，可选）──
MINERU_TOKENS=token1,token2,token3
```

> `MINERU_TOKENS` 支持多个 Token 逗号分隔，系统自动轮询并在额度用完后切换。

### 3. 安装依赖

```bash
# 推荐使用 conda + uv
conda activate rag_test   # 或自己创建环境
uv sync
```

### 4. 初始化索引

```bash
uv run python scripts/init_es.py       # 创建 ES 索引（ik_smart 分词）
uv run python scripts/init_milvus.py   # 创建 Milvus Collection
```

### 5. 下载向量模型（可选）

```bash
uv run python scripts/download_model.py
# 模型文件会下载到 models/ 目录
```

### 6. 启动 API 服务

```bash
# 开发模式（热重载）
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

API 文档地址：http://localhost:8000/docs

---

## 📄 PDF 文档处理完整流程

### （可选）回填预置文献

如果文献数据已通过其他渠道导入 ES / MinIO（即"预置文献"），可用此脚本把它们同步到 `document_tasks` 数据库表，使其在管理界面中可见并支持删除操作：

```bash
uv run python scripts/backfill_document_tasks.py
```

脚本逻辑：
1. 从 ES `chunks` 索引扫描所有 L0 chunk，获取 `doc_id`、`md5`、`title_cn`
2. 用 `md5` 在 MinIO `raw-docs` 桶中查找对应 PDF 路径
3. 在 `document_tasks` 表创建状态为 `READY` 的记录，`batch_id` 字段存 ES 的 `doc_id`（删除时用于精准清理 ES / Milvus）

> `batch_id` 的作用：预置文献在 ES 中以 `doc_id`（如 `"7597"`）而非 `md5` 标识，删除时系统会优先用 `batch_id` 定位并清除 ES / Milvus 中的所有 chunk。

> PDF 预览功能已改为后端代理模式，无需运行此脚本即可查看预置文献的 PDF。仅在需要对预置文献重新走解析流水线时才需要运行。

### 阶段一：上传与解析

```bash
# 1. 将 PDF 放入 after/ 目录（或修改 .env 中的 PDF_INPUT_DIR）
# 2. 批量提交到 MinerU 解析
uv run python scripts/scan_submit.py

# 3. 启动 Worker 轮询解析结果
uv run python -c "from src.worker import run_worker; run_worker()"
```

Worker 会自动将 `pending → processing → parsed` 更新状态，并将解析产物存到 MinIO。

### 阶段二：文档切分

```bash
uv run python scripts/run_chunker.py --upload --out-dir ./chunks
```

参数说明：
- `--upload` — 切分完成后上传到 MinIO `chunks` 桶
- `--out-dir` — 本地输出目录（默认 `./chunks`）
- 支持断点续跑和失败隔离

### 阶段三：导入索引

```bash
# 导入到 Elasticsearch
uv run python scripts/import_es.py --dir ./chunks

# 导入到 Milvus
uv run python scripts/import_milvus.py --dir ./chunks --mode batch --device cuda:0
# --device cuda:0 使用 GPU 编码，不加则使用 CPU
```

### 检查状态

```bash
# 检查 ES 文档数
curl "http://localhost:9200/chunks/_count"

# 检查 Milvus 数据量
# 通过 Attu 面板 http://localhost:8000 查看
```

---

## 🔍 RAG 检索与问答 API

### Python SDK 调用

```python
from src.search import search, search_with_intent, search_and_answer

# 1. 纯检索
hits = search("高血压的药物选择", top_k=20)
for h in hits:
    print(f"[{h.level}] {h.content[:100]}...")

# 带过滤条件
hits = search("高血压的药物选择", filters={"level": "L1"}, top_k=20)

# 2. 意图识别 + 检索
hits, intent = search_with_intent("儿童发热怎么用药", top_k=20)
print(f"覆盖度: {intent.coverage}")       # full / partial / none
print(f"建议: {intent.suggestion}")

# 3. 检索 + Rerank + LLM 回答（非流式）
result = search_and_answer(
    query="高血压患者应该如何选择降压药物？",
    top_k=10
)
print(result.answer)          # LLM 回答文本
for s in result.sources:      # 引用来源
    print(f"[{s.idx}] {s.title}")

# 4. 流式回答（SSE）
stream = search_and_answer(
    query="高血压患者应该如何选择降压药物？",
    stream=True
)
for token in stream:
    print(token, end="")
```

### HTTP API

```bash
# 检索 + 回答
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"query": "高血压的药物选择", "top_k": 10}'

# 流式回答
curl -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"query": "高血压的药物选择", "top_k": 10}' \
  --no-buffer

# PDF 预览（后代理流，避免前端直连 MinIO 的 CORS 问题）
curl http://localhost:8000/api/v1/documents/{doc_id}/pdf/stream \
  -H "Authorization: Bearer <token>" \
  --output preview.pdf
```

---

## 🧪 运行测试

```bash
cd backend

# 意图识别（验证领域分类/覆盖度判断）
uv run python test/test_query_intent.py

# Reranker 精排（API + 链路测试）
uv run python test/test_siliconflow_rerank.py

# LLM 回答（同步/流式/完整管线）
uv run python test/test_llm_answer.py

# 向量编码一致性（BGE-M3 编码校验）
uv run python test/test_embedding_compat.py

# MinerU API 测试
uv run python test/test_mineru.py
```

---

## 🔧 配置参考

完整配置项见 `.env.example`，关键配置分组：

### 数据库连接

```ini
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=mineru
POSTGRES_PASSWORD=mineru123
POSTGRES_DB=mineru_pipeline
```

### MinIO 四桶

```ini
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_RAW_BUCKET=raw-docs        # 原始 PDF
MINIO_META_BUCKET=doc-meta       # PDF 元信息
MINIO_PARSED_BUCKET=parsed-data  # 解析产物 (full.md / images)
# chunks 桶在 chunker 中固定使用
```

### MinerU 解析参数

```ini
MINERU_MODEL_VERSION=vlm
MINERU_ENABLE_OCR=false
MINERU_ENABLE_FORMULA=true
MINERU_ENABLE_TABLE=true
MINERU_LANGUAGE=ch
MINERU_MAX_PAGES_PER_KEY=1000    # 每个 Token 每日上限
MINERU_BATCH_SIZE=10             # 每批提交文件数
```

---

## 🏗️ 检索管线详解

```
query
  │
  ├── [Intent Recognition] DeepSeek V4 Flash
  │     → domain: 高血压 | coverage: partial | rewritten_query: ...
  │     → suggestion: "建议补充患者年龄信息"
  │
  ├── [Vector Retrieval] Milvus (topK=200, COSINE, BGE-M3 1024dim)
  │     → chunk_ids + score_m
  │
  ├── [BM25 Retrieval] ES (topK=200, ik_smart)
  │     → chunk_ids + score_e
  │
  ▼
[RRF Fusion] score = 1/(60+rank_m) + 1/(60+rank_e)
  │
  ▼
[Rerank] Qwen3-Reranker-4B (硅基流动 API)
  │     → 重新排序并过滤低分文档
  │
  ▼
[LLM Answer] DeepSeek V4 Pro
  │     → 仅使用提供的文献作答，引用 [N] 标注
  │     → 覆盖度不足时输出提示
  │
  ▼
AnswerResult(answer, sources, intent)
```

---

## 📊 三粒度 Chunk 结构

| Level | Chunk Type  | 每篇数量 | 内容                               | ES 字段重点                        |
| ----- | ----------- | -------- | ---------------------------------- | ---------------------------------- |
| L0    | `paper`     | 1        | 刊名/DOI/标题/摘要/关键词         | `title_cn`, `abstract`, `keywords` |
| L1    | `paragraph` | ~18      | 章节坐标 + 正文段落               | `heading_stack`, `content` (BM25)  |
| L2    | `table`     | ~3       | 坐标 + 作者结论 + HTML 表格       | `table_caption`, `html_body`       |

> L1/L2 的 `content` 同时进入 Milvus 向量索引。

---

## 🐳 Docker 常用命令

```bash
# 启动全部服务
docker compose up -d

# 启动单个服务
docker compose up -d elasticsearch kibana
docker compose up -d milvus

# 查看日志
docker compose logs -f worker

# 停止全部
docker compose down

# 停止并删除数据卷（谨慎！）
docker compose down -v

# 重启某个服务
docker compose restart elasticsearch
```

---

## ❗ 常见问题

**ES 启动失败？**
确保提前下载了 IK 分词器插件包放到 `data/plugins/` 目录：
```bash
wget https://github.com/medcl/elasticsearch-analysis-ik/releases/download/v8.19.15/elasticsearch-analysis-ik-8.19.15.zip
mv elasticsearch-analysis-ik-8.19.15.zip data/plugins/
```

**Milvus 启动慢？**
首次启动需要下载镜像和创建索引，耐心等待 1-2 分钟。可以通过 `docker compose logs -f milvus` 查看进度。

**Worker 提示连接失败？**
确保 `.env` 中的 Redis / MinIO 连接参数与 `docker-compose.yml` 一致。

**uv sync 失败？**
确认 conda 环境已激活，Python 版本 ≥ 3.10。如果 torch 安装慢，可以单独安装 CUDA 版本的 torch。

---

## 📝 开发说明

- 包管理使用 **uv**，同步后生成 `uv.lock` 保证依赖一致性
- 添加依赖: `uv add <package>`
- 运行脚本: `uv run python <script.py>`
- 所有基础设施数据持久化在 `data/` 目录（已 gitignore）
- 模型文件下载到 `models/` 目录（已 gitignore）
- API 部署可通过 `pyproject.toml` 中定义的 `pipeline-api` 入口点
