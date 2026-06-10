# Claude Code Context — MinerU Pipeline + Chunker + RAG

---

## 1. 系统架构

```
                    ┌──────────────────┐
                    │   客户端上传 PDF  │
                    └────────┬─────────┘
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
                           │  Chunker  │ L0/L1/L2
                           └─────┬─────┘
                                 ▼
                     ┌─────────────────────┐
                     │  ES BM25 + Milvus   │
                     │  双路索引 (28759条) │
                     └──────────┬──────────┘
                                ▼
┌─────────┐   ┌─────────────────────────────────────┐
│ 用户    │──▶│ Query Intent (DeepSeek-V4-Flash)    │
│ Query   │   │ → 领域分类 / 覆盖度 / Query重写     │
└─────────┘   └──────────────────┬──────────────────┘
                                ▼
                     ┌─────────────────────┐
                     │  ES BM25 + Milvus   │
                     │  双路召回 → RRF融合 │
                     └──────────┬──────────┘
                                ▼
                     ┌─────────────────────┐
                     │ Qwen3-Reranker-4B   │
                     │ 硅基流动 API 精排   │
                     └──────────┬──────────┘
                                ▼
                     ┌─────────────────────┐
                     │ DeepSeek-V4-Pro     │
                     │ LLM 回答 + 引用     │
                     └─────────────────────┘
```

### 状态机

```
pending → processing → parsed → chunked → (ES + Milvus)
                    ↘ failed → (重试时重置为 pending)
```

---

## 2. 环境状况dd

| 项目       | 详情                                                              |
| ---------- | ----------------------------------------------------------------- |
| OS         | Windows 11 Pro for Workstations 10.0.26200                        |
| Shell      | Git Bash (Unix 语法，路径用正斜杠)                                |
| Python     | Conda 环境 `rag_test`, Python 3.12.13                           |
| 包管理     | **uv** (只在 `rag_test` conda 环境中可用)                 |
| 虚拟环境   | `.venv/` (uv 自动管理)                                          |
| 基础设施   | Docker (PostgreSQL + Redis + MinIO + ES + Kibana + Milvus + etcd) |
| 数据持久化 | `./data/` 下各服务独立目录                                      |

### Docker 容器

| 服务          | 镜像                                | 端口                          |
| ------------- | ----------------------------------- | ----------------------------- |
| PostgreSQL    | `postgres:16-alpine`              | 5432                          |
| Redis         | `redis:7.4.8`                     | 6379                          |
| MinIO         | `cgr.dev/chainguard/minio:latest` | 9000 (API), 9001 (Console)    |
| Elasticsearch | `elasticsearch:8.19.15`           | 9200 (REST), 9300 (Transport) |
| Kibana        | `kibana:8.19.15`                  | 5601                          |
| Milvus        | `milvusdb/milvus:v2.4.15`         | 19530 (gRPC), 9091 (Health)   |
| etcd          | `quay.io/coreos/etcd:v3.5.5`      | 2379                          |
| Attu          | `zilliz/attu:v2.4.12`             | 8000 (GUI)                    |

### 目录结构

```
project/
├── after/                  # 测试用 PDF 文件
├── data/                   # Docker 数据卷持久化 (gitignore)
│   ├── postgres/           # PostgreSQL 数据
│   ├── redis/              # Redis 数据
│   ├── minio/              # MinIO 数据
│   ├── elasticsearch/      # ES 数据
│   ├── milvus/             # Milvus 数据
│   ├── etcd/               # etcd 数据
│   └── plugins/            # ES 插件 (IK 分词器)
├── models/                 # bge-m3 模型文件 (gitignore)
├── chunks/                 # chunk JSON 输出目录 (gitignore)
├── log/                    # 运行日志 (gitignore)
├── docs/                   # 踩坑记录文档
│   ├── milvus-deployment-troubleshooting.md
│   ├── storage-import-troubleshooting.md
│   ├── refactor-langchain-plan.md
│   └── llm-answer-plan.md
├── src/                    # 核心代码
│   ├── config.py           # 全局配置
│   ├── db.py               # SQLAlchemy 异步引擎
│   ├── models.py           # ORM 模型
│   ├── schemas.py          # Pydantic 模型
│   ├── key_manager.py      # 多 Token 额度管理器
│   ├── redis_client.py     # Redis 队列操作
│   ├── minio_client.py     # MinIO 四桶操作
│   ├── mineru_client.py    # MinerU API v4 客户端
│   ├── chunker.py          # 三粒度分层切分
│   ├── search.py           # 双路检索 + RRF + Rerank + search_and_answer
│   ├── query_intent.py     # DeepSeek-V4-Flash 意图识别
│   ├── reranker.py         # SiliconFlow Reranker (LangChain BaseDocumentCompressor)
│   ├── llm.py              # 模型工厂 (ChatOpenAI / HuggingFaceEmbeddings)
│   ├── llm_answer.py       # LLM 回答生成 (DeepSeek-V4-Pro, 流式)
│   ├── worker.py           # 后台轮询 Worker
│   └── main.py             # FastAPI 应用
├── scripts/                # 数据处理脚本
│   ├── scan_submit.py      # 文件夹扫描提交器
│   ├── run_chunker.py      # 批量切分
│   ├── download_model.py   # 下载 bge-m3 模型
│   ├── init_es.py          # ES 索引初始化 (IK分词器)
│   ├── init_milvus.py      # Milvus Collection 初始化
│   ├── import_es.py        # 批量导入 chunks → ES
│   └── import_milvus.py    # 批量导入 chunks → Milvus
├── deploy/                 # 服务端部署包
├── test/                   # 测试
│   ├── test_query_intent.py      # 意图识别 (8 case, 8/8)
│   ├── test_siliconflow_rerank.py # Reranker API + 链路
│   ├── test_llm_answer.py        # LLM 回答 sync/stream/pipeline
│   ├── test_embedding_compat.py  # 向量编码一致性验证
│   ├── test_mineru.py
│   ├── test_mineru_keys.py
│   └── test_pipeline.py
├── docker-compose.yml
├── pyproject.toml
├── .env
└── CLAUDE.md
```

### MinIO 四桶

| 桶名            | 用途            | 路径格式                              |
| --------------- | --------------- | ------------------------------------- |
| `raw-docs`    | 原始 PDF 备份   | `{MD5}/{filename}`                  |
| `doc-meta`    | PDF 元信息 JSON | `{MD5}/{filename}.json`             |
| `parsed-data` | 解析产物        | `{MD5}/full.md`, `{MD5}/images/*` |
| `chunks`      | 切分结果 JSON   | `{uuid}.json`                       |

---

## 3. 外部 API

| 服务     | 用途                | 模型                                        | Key 位置                         |
| -------- | ------------------- | ------------------------------------------- | -------------------------------- |
| DeepSeek | 意图识别 + LLM 回答 | `deepseek-v4-flash` / `deepseek-v4-pro` | `.env` `DEEPSEEK_API_KEY`    |
| 硅基流动 | Reranker            | `Qwen/Qwen3-Reranker-4B`                  | `.env` `SILICONFLOW_API_KEY` |

---

## 4. 工具用法

### 基础设施

```bash
# 启动全部服务
docker compose up -d

# 启动单个
docker compose up -d elasticsearch kibana
docker compose up -d milvus
docker compose up -d attu

# ES 健康
curl http://localhost:9200/_cluster/health

# Attu 面板: http://localhost:8000
# Kibana: http://localhost:5601
```

### Python 依赖管理

```bash
source D:/anaconda/Scripts/activate rag_test   # 激活 conda
uv sync                                          # 安装依赖
uv add <package>                                  # 添加依赖
uv run python <script.py>                         # 运行脚本
```

### Chunker 切分

```bash
uv run python scripts/run_chunker.py --out-dir ./chunks
uv run python scripts/run_chunker.py --upload --out-dir ./chunks
```

### ES + Milvus 导入

```bash
uv run python scripts/init_es.py
uv run python scripts/init_milvus.py
uv run python scripts/import_es.py --dir ./chunks
python scripts/import_milvus.py --dir ./chunks --mode batch --device cuda:0
```

### 检索 + 回答 (Python API)

```python
from src.search import search, search_and_answer

# 仅检索
hits = search("高血压的药物选择", filters={"level": "L1"}, top_k=20)

# 意图识别 + 检索
hits, intent = search_with_intent("儿童发热怎么用药", top_k=20)
print(intent.coverage, intent.suggestion)

# 检索 + Rerank + LLM 回答 (非流式)
result = search_and_answer("高血压的药物选择", top_k=10)
print(result.answer)

# 流式
stream = search_and_answer("高血压的药物选择", stream=True)
for token in stream:
    print(token, end="")
```

### 测试

```bash
# 意图识别
uv run python test/test_query_intent.py

# Reranker
uv run python test/test_siliconflow_rerank.py

# LLM 回答 (含流式)
uv run python test/test_llm_answer.py

# Embedding 一致性验证
uv run python test/test_embedding_compat.py
```

### 下载模型

```bash
uv run python scripts/download_model.py
```

---

## 5. Chunk 三层结构

| Level | Chunk Type    | 每篇数量 | 内容                       |
| ----- | ------------- | -------- | -------------------------- |
| L0    | `paper`     | 1        | 刊名/DOI/标题/摘要/关键词  |
| L1    | `paragraph` | ~18      | 章节坐标 + 正文段落        |
| L2    | `table`     | ~3       | 章节坐标 + 作者结论 + HTML |

### Chunk 字段分库

| 字段                                      | L0 | L1 | L2 | Milvus | ES                 |
| ----------------------------------------- | -- | -- | -- | ------ | ------------------ |
| `chunk_id`                              | ✓ | ✓ | ✓ | PK     | keyword            |
| `doc_id`                                | ✓ | ✓ | ✓ | 标量   | keyword            |
| `doi`                                   | ✓ | ✓ | ✓ | 标量   | keyword            |
| `level`                                 | ✓ | ✓ | ✓ | 标量   | keyword            |
| `chunk_type`                            | ✓ | ✓ | ✓ | 标量   | keyword            |
| `journal/section/article_type/title_cn` | ✓ | — | — | 标量   | keyword/text       |
| `heading_stack/heading_depth`           | — | ✓ | ✓ | —     | keyword/short      |
| `table_number/table_caption/html_size`  | — | — | ✓ | —     | short/text/int     |
| `refers_to_tables`                      | — | ✓ | — | —     | keyword[]          |
| `content`                               | ✓ | ✓ | ✓ | →向量 | text (BM25)        |
| `html_body`                             | — | — | ✓ | —     | text (index:false) |

---

## 6. 检索管线 (已全部闭环)

```
query
  │
  ├── Intent Recognition (DeepSeek-V4-Flash)
  │     → domain / coverage / rewritten_query / suggestion
  │
  ├── Milvus 向量检索 (topK=200, COSINE, bge-m3 1024dim)
  │     ← chunk_ids + score_m
  │
  ├── ES BM25 全文检索 (topK=200, ik_smart)
  │     ← chunk_ids + score_e
  │
  ▼
RRF 融合: score = 1/(60+rank_m) + 1/(60+rank_e)
  │
  ▼
Qwen3-Reranker-4B 精排 (硅基流动 API)
  │
  ▼
DeepSeek-V4-Pro LLM 回答 (流式/非流式)
  │  规则: 只使用提供文献作答，引用 [N] 标注
  │  覆盖度不足时输出提示
  │
  ▼
AnswerResult(answer, sources, intent)
```

---

## 7. 每个文件的用途

### 核心源码 (`src/`)

| 文件                | 用途                                                                  |
| ------------------- | --------------------------------------------------------------------- |
| `config.py`       | 全局配置 (PG/Redis/MinIO/ES/Milvus/DeepSeek/硅基流动)                 |
| `llm.py`          | 模型工厂:`get_chat_model()` / `get_embedding_model()` (LangChain) |
| `query_intent.py` | DeepSeek-V4-Flash 意图识别: 领域分类 + 覆盖度 + query 重写            |
| `search.py`       | 双路检索 + RRF + Rerank +`search_and_answer()` 一键管线             |
| `reranker.py`     | SiliconFlow Qwen3-Reranker-4B (BaseDocumentCompressor)                |
| `llm_answer.py`   | DeepSeek-V4-Pro 回答生成 + 流式输出 + context 拼装                    |
| `chunker.py`      | 三粒度切分: full.md → L0/L1/L2                                       |
| `minio_client.py` | MinIO 四桶操作                                                        |
| `worker.py`       | 后台轮询 Worker                                                       |
| `main.py`         | FastAPI 网关                                                          |

### 脚本 (`scripts/`)

| 文件                  | 用途                                       |
| --------------------- | ------------------------------------------ |
| `run_chunker.py`    | 批量切分 (断点续跑/失败隔离/原子写入/日志) |
| `download_model.py` | 下载 bge-m3 (多源降级)                     |
| `init_es.py`        | ES 索引初始化 (IK分词器)                   |
| `init_milvus.py`    | Milvus Collection 初始化                   |
| `import_es.py`      | 批量导入 chunks → ES                      |
| `import_milvus.py`  | 批量导入 chunks → Milvus                  |
