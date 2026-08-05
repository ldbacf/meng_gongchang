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

前置条件：Python ≥ 3.10（推荐 3.12）、Node.js ≥ 18、Docker & Docker Compose。

```bash
# 1. 启动基础设施（PostgreSQL / Redis / MinIO / ES / Milvus 等）
cd backend && docker compose up -d

# 2. 配置环境变量
cp .env.example .env   # 填入 DEEPSEEK_API_KEY / SILICONFLOW_API_KEY / MINERU_TOKENS

# 3. 后端（conda + uv）
source D:/anaconda/Scripts/activate rag_test
uv sync
uv run python scripts/init_es.py && uv run python scripts/init_milvus.py
uv run uvicorn src.main:app --reload --port 8000

# 4. 前端
cd frontend && npm install && npm run dev   # http://localhost:5173
```

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
