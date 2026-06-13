# MedRAG — 医疗领域 RAG 智能问答系统

> **Medical Retrieval-Augmented Generation Assistant**  
> 基于 PDF 文档解析、双路检索引擎与 LLM 的医疗文献问答助手。

---

## 📋 项目概览

MedRAG 是一个面向基层医疗场景的 RAG 智能问答系统，实现了从 PDF 文档上传、解析、切分、向量化存储到智能检索与 LLM 回答的完整管线。

**核心流程：**

```
上传 PDF → MinerU 解析 → 三粒度切分 (L0/L1/L2) → ES BM25 + Milvus 向量双路索引
                                                          ↓
用户 Query → DeepSeek 意图识别 → 双路召回 → RRF 融合 → Reranker 精排 → LLM 回答
```

---

## 🏗️ 系统架构

```
                    ┌──────────────────┐
                    │   前端 Vue 3 应用 │
                    └────────┬─────────┘
                             │ HTTP / SSE
                             ▼
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ 客户端   │────▶│ FastAPI  │────▶│ MinerU   │────▶│  Worker  │
│ 上传 PDF │     │ 网关     │     │ API v4   │     │ 后台轮询 │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                       │                                 │
                       ▼                                 ▼
                ┌──────────┐                      ┌──────────┐
                │PostgreSQL│                      │  MinIO   │
                │ 业务账本 │                      │ 四桶存储 │
                └──────────┘                      └──────────┘
                       │                                 │
                       └──────────┬──────────────────────┘
                                  ▼
                           ┌──────────┐
                           │  Chunker  │ L0 / L1 / L2
                           └─────┬─────┘
                                 ▼
                     ┌─────────────────────┐
                     │  ES BM25  +  Milvus  │
                     │  双路索引            │
                     └──────────┬──────────┘
                                ▼
┌─────────┐   ┌─────────────────────────────┐
│ 用户    │──▶│ Query Intent (DeepSeek)     │
│ Query   │   │ → 领域分类 / 覆盖度 / 重写  │
└─────────┘   └──────────────┬──────────────┘
                             ▼
                     ┌─────────────────────┐
                     │  双路召回 → RRF 融合 │
                     └──────────┬──────────┘
                                ▼
                     ┌─────────────────────┐
                     │ Qwen3-Reranker-4B   │
                     │ 硅基流动 API 精排   │
                     └──────────┬──────────┘
                                ▼
                     ┌─────────────────────┐
                     │ DeepSeek V4 Pro     │
                     │ LLM 回答 + 文献引用 │
                     └─────────────────────┘
```

### 文档状态机

```
pending → processing → parsed → chunked → (ES + Milvus)
                    ↘ failed → (重试时重置为 pending)
```

---

## 🧩 技术栈

| 层次       | 技术                                                                                 |
| ---------- | ------------------------------------------------------------------------------------ |
| **前端**   | Vue 3 + TypeScript + Vite + Pinia + Vue Router + Tailwind CSS                        |
| **后端**   | Python 3.12 + FastAPI + SQLAlchemy (async) + LangChain                                |
| **数据库** | PostgreSQL (业务数据) + Redis (队列) + Elasticsearch (BM25) + Milvus (向量检索)       |
| **存储**   | MinIO (对象存储: 原始 PDF / 元信息 / 解析产物 / 切分结果)                            |
| **外部API**| DeepSeek (意图识别 + 回答生成) · SiliconFlow (Reranker) · MinerU (PDF解析)            |
| **向量**   | BGE-M3 模型 (1024维, COSINE 相似度)                                                  |
| **容器**   | Docker Compose (PostgreSQL / Redis / MinIO / ES / Kibana / Milvus / etcd / Attu)    |

---

## 📁 目录结构

```
medrag/
├── backend/                    # Python 后端
│   ├── src/                    # 核心源码
│   │   ├── main.py             # FastAPI 应用入口
│   │   ├── config.py           # 全局配置 (各服务连接参数)
│   │   ├── db.py               # SQLAlchemy 异步引擎
│   │   ├── auth.py             # JWT 认证
│   │   ├── key_manager.py      # MinerU 多 Token 额度管理器
│   │   ├── redis_client.py     # Redis 队列操作
│   │   ├── minio_client.py     # MinIO 四桶操作
│   │   ├── mineru_client.py    # MinerU API v4 客户端
│   │   ├── chunker.py          # 三粒度分层切分 (L0/L1/L2)
│   │   ├── search.py           # 双路检索 + RRF + Rerank + 回答
│   │   ├── query_intent.py     # DeepSeek 意图识别
│   │   ├── reranker.py         # SiliconFlow Reranker 封装
│   │   ├── llm.py              # LangChain 模型工厂
│   │   ├── llm_answer.py       # LLM 回答生成 (流式/非流式)
│   │   ├── worker.py           # 后台轮询 Worker
│   │   └── routers/            # API 路由
│   ├── scripts/                # 数据处理脚本
│   │   ├── scan_submit.py      # 批量扫描提交 PDF
│   │   ├── run_chunker.py      # 批量切分
│   │   ├── backfill_document_tasks.py # 回填预置文献到 document_tasks 表
│   │   ├── init_es.py          # ES 索引初始化
│   │   ├── init_milvus.py      # Milvus 集合初始化
│   │   ├── import_es.py        # 导入切分结果 → ES
│   │   ├── import_milvus.py    # 导入切分结果 → Milvus
│   │   └── download_model.py   # 下载 BGE-M3 模型
│   ├── test/                   # 测试
│   ├── docker-compose.yml      # 基础设施容器编排
│   ├── pyproject.toml          # Python 项目配置
│   └── .env.example            # 环境变量模板
│
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── api/                # API 客户端 (axios, 请求/响应拦截)
│   │   ├── components/         # 组件
│   │   │   ├── chat/           # 对话相关 (MessageBubble, CitationCard, PdfViewer...)
│   │   │   ├── common/         # 通用组件 (AppLogo, LoadingSpinner, ToastContainer)
│   │   │   ├── layout/         # 布局组件 (AppLayout, Sidebar)
│   │   │   └── admin/          # 管理组件 (UserManagement)
│   │   ├── composables/        # 组合式函数 (useAuth, useSSE, useMarkdown)
│   │   ├── stores/             # Pinia 状态管理 (auth, toast)
│   │   ├── types/              # TypeScript 类型定义
│   │   └── views/              # 页面视图 (ChatView, UserManagementView)
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── package.json
│
└── README.md
```

---

## 🚀 快速开始

### 前置条件

- Python ≥ 3.10（推荐 3.12）
- Node.js ≥ 18
- Docker & Docker Compose
- CUDA 设备（可选，用于 BGE-M3 编码加速）

### 1. 启动基础设施

```bash
cd backend
docker compose up -d
```

启动的服务:

| 服务          | 端口                    | 说明                        |
| ------------- | ----------------------- | --------------------------- |
| PostgreSQL    | `5432`                  | 业务数据                    |
| Redis         | `6379`                  | 任务队列                    |
| MinIO         | `9000` (API) `9001` (Console) | 对象存储           |
| Elasticsearch | `9200` (REST)           | BM25 全文检索 + IK 分词器   |
| Kibana        | `5601`                  | ES 可视化                   |
| Milvus        | `19530` (gRPC)          | 向量检索                    |
| etcd          | `2379`                  | Milvus 元数据               |
| Attu          | `8000` (GUI)            | Milvus 管理面板             |

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key:
#   DEEPSEEK_API_KEY     — DeepSeek API 密钥
#   SILICONFLOW_API_KEY  — 硅基流动 API 密钥
#   MINERU_TOKENS        — MinerU API 令牌（可选，用于 PDF 解析）
```

### 3. 后端

```bash
cd backend
# 推荐使用 uv + conda
source D:/anaconda/Scripts/activate rag_test
uv sync

# 初始化 ES 索引与 Milvus 集合
uv run python scripts/init_es.py
uv run python scripts/init_milvus.py

# 启动 API 服务
uv run uvicorn src.main:app --reload --port 8000
```

### 4. 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，API 代理到 `http://localhost:8000`。

---

## 📄 PDF 文档处理流程

### 批量上传与解析

```bash
# 将 PDF 放入 after/ 目录，批量提交到 MinerU 解析
uv run python scripts/scan_submit.py

# 启动后台 Worker 轮询解析结果
uv run python -c "from src.worker import run_worker; run_worker()"
```

### 回填预置文献（可选）

如果文献已通过其他渠道导入 ES / MinIO，用此脚本将其同步到 `document_tasks` 数据库表，使其在管理界面可见并支持删除：

```bash
uv run python scripts/backfill_document_tasks.py
```

### 文档切分 (Chunking)

三粒度分层切分:

| Level | 类型        | 每篇数量 | 内容                        |
| ----- | ----------- | -------- | --------------------------- |
| L0    | `paper`     | 1        | 刊名/DOI/标题/摘要/关键词   |
| L1    | `paragraph` | ~18      | 章节坐标 + 正文段落         |
| L2    | `table`     | ~3       | 章节坐标 + 作者结论 + HTML  |

```bash
# 批量切分并上传到 MinIO
uv run python scripts/run_chunker.py --upload --out-dir ./chunks
```

### 导入索引

```bash
# 导入到 ES
uv run python scripts/import_es.py --dir ./chunks

# 导入到 Milvus
uv run python scripts/import_milvus.py --dir ./chunks --mode batch --device cuda:0
```

---

## 🔍 检索与问答

### 检索管线

```
query → 意图识别 (DeepSeek V4 Flash)
         → 领域分类 / 覆盖度判断 / Query 重写 / 建议
      → Milvus 向量召回 (topK=200, COSINE, BGE-M3)
      → ES BM25 召回 (topK=200, ik_smart)
      → RRF 融合 (score = 1/(60+rank_m) + 1/(60+rank_e))
      → Qwen3-Reranker-4B 精排 (硅基流动 API)
      → DeepSeek V4 Pro 回答生成 (流式/非流式)
         → 仅基于提供文献作答，标注引用 [N]
```

### API 调用

```python
from src.search import search, search_and_answer

# 仅检索
hits = search("高血压的药物选择", filters={"level": "L1"}, top_k=20)

# 检索 + 意图识别
hits, intent = search_with_intent("儿童发热怎么用药", top_k=20)
print(intent.coverage, intent.suggestion)

# 检索 + Rerank + LLM 回答
result = search_and_answer("高血压的药物选择", top_k=10)
print(result.answer)

# 流式回答
stream = search_and_answer("高血压的药物选择", stream=True)
for token in stream:
    print(token, end="")
```

---

## 🧪 测试

```bash
cd backend

# 意图识别测试
uv run python test/test_query_intent.py

# Reranker 测试
uv run python test/test_siliconflow_rerank.py

# LLM 回答测试 (含流式)
uv run python test/test_llm_answer.py

# 向量编码一致性验证
uv run python test/test_embedding_compat.py
```

---

## 🖥️ 前端功能

- **对话界面** — 类 ChatGPT 交互式问答，支持流式 SSE 输出
- **文献引用** — 回答结果附带文献引用卡片，点击可查看原文
- **PDF 预览** — 内嵌 PDF 查看器，定位到引用位置
- **用户认证** — JWT 登录 + Token 自动刷新
- **用户管理** — 后台用户管理面板
- **响应式布局** — 可折叠侧栏，桌面/移动端自适应

---

## ⚙️ 环境要求

### MinIO 四桶

| 桶名           | 用途            | 路径格式                    |
| -------------- | --------------- | --------------------------- |
| `raw-docs`     | 原始 PDF 备份   | `{MD5}/{filename}`          |
| `doc-meta`     | PDF 元信息 JSON | `{MD5}/{filename}.json`     |
| `parsed-data`  | MinerU 解析产物 | `{MD5}/full.md`, `images/*` |
| `chunks`       | 切分结果 JSON   | `{uuid}.json`               |

### 外部 API

| 服务       | 用途                    | 模型                                          | 配置项                    |
| ---------- | ----------------------- | --------------------------------------------- | ------------------------- |
| **DeepSeek** | 意图识别 + 回答生成 | `deepseek-v4-flash` / `deepseek-v4-pro`      | `DEEPSEEK_API_KEY`      |
| **硅基流动** | Reranker 精排          | `Qwen/Qwen3-Reranker-4B`                   | `SILICONFLOW_API_KEY`   |
| **MinerU** | PDF 解析引擎            | 多 Token 轮询，自动超限切换                   | `MINERU_TOKENS`         |

---

## 📝 开发说明

- 后端依赖通过 `uv sync` 管理，锁定在 `uv.lock`
- 前端依赖通过 `npm` 管理
- ES 使用 IK 分词器 (`ik_smart` / `ik_max_word`) 进行中文分词
- 向量模型 BGE-M3 下载到 `models/` 目录（需手动运行 `download_model.py`）
- 所有基础设施数据持久化在 `data/` 目录（已 gitignore）

---

## 📄 开源许可

MIT License
