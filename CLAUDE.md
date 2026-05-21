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
                           │  Redis   │
                           │ 任务队列 │
                           └──────────┘

                    ┌──────────────────┐
                    │  Chunker 切分    │
                    │ L0/L1/L2 → JSON  │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  ES + Milvus 导入 │
                    │  双路检索 + Rerank│
                    └──────────────────┘
```

### 状态机

```
pending → processing → parsed → chunked → (ES + Milvus)
                    ↘ failed → (重试时重置为 pending)
```

---

## 2. 环境状况

| 项目 | 详情 |
|---|---|
| OS | Windows 11 Pro for Workstations 10.0.26200 |
| Shell | Git Bash (Unix 语法，路径用正斜杠) |
| Python | Conda 环境 `rag_test`, Python 3.12.13 |
| 包管理 | **uv** (只在 `rag_test` conda 环境中可用) |
| 虚拟环境 | `.venv/` (uv 自动管理) |
| 基础设施 | Docker (PostgreSQL + Redis + MinIO + ES + Kibana + Milvus + etcd) |
| 数据持久化 | `./data/` 下各服务独立目录 |

### Docker 容器

| 服务 | 镜像 | 端口 |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | 5432 |
| Redis | `redis:7.4.8` | 6379 |
| MinIO | `cgr.dev/chainguard/minio:latest` | 9000 (API), 9001 (Console) |
| Elasticsearch | `elasticsearch:8.19.15` | 9200 (REST), 9300 (Transport) |
| Kibana | `kibana:8.19.15` | 5601 |
| Milvus | `milvusdb/milvus:v2.4.15` | 19530 (gRPC), 9091 (Health) |
| etcd | `quay.io/coreos/etcd:v3.5.5` | 2379 |
| Attu | `zilliz/attu:v2.4.12` | 8000 (GUI) |

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
│   └── storage-import-troubleshooting.md
├── src/                    # 核心代码
│   ├── config.py           # 全局配置 (含 ES/Milvus)
│   ├── db.py               # SQLAlchemy 异步引擎
│   ├── models.py           # ORM 模型
│   ├── schemas.py          # Pydantic 模型
│   ├── key_manager.py      # 多 Token 额度管理器
│   ├── redis_client.py     # Redis 队列操作
│   ├── minio_client.py     # MinIO 四桶操作
│   ├── mineru_client.py    # MinerU API v4 客户端
│   ├── chunker.py          # 三粒度分层切分
│   ├── search.py           # 双路检索 + RRF + Rerank
│   ├── worker.py           # 后台轮询 Worker
│   └── main.py             # FastAPI 应用
├── scripts/
│   ├── scan_submit.py      # 文件夹扫描提交器
│   ├── run_chunker.py      # 批量切分 (断点续跑/隔离/原子写入)
│   ├── download_model.py   # 下载 bge-m3 模型
│   ├── init_es.py          # ES 索引初始化 (IK分词器)
│   ├── init_milvus.py      # Milvus Collection 初始化
│   ├── import_es.py        # 批量导入 chunks → ES
│   └── import_milvus.py    # 批量导入 chunks → Milvus
├── deploy/                 # 服务端部署包
├── test/
│   ├── test_mineru.py
│   ├── test_mineru_keys.py
│   └── test_pipeline.py
├── docker-compose.yml
├── pyproject.toml
├── .env
└── CLAUDE.md
```

### MinIO 四桶

| 桶名 | 用途 | 路径格式 |
|---|---|---|
| `raw-docs` | 原始 PDF 备份 | `{MD5}/{filename}` |
| `doc-meta` | PDF 元信息 JSON | `{MD5}/{filename}.json` |
| `parsed-data` | 解析产物 | `{MD5}/full.md`, `{MD5}/images/*` |
| `chunks` | 切分结果 JSON | `{uuid}.json` |

---

## 3. 工具用法

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
# 全量切分
uv run python scripts/run_chunker.py --out-dir ./chunks

# 切分 + 上传 MinIO chunks 桶
uv run python scripts/run_chunker.py --upload --out-dir ./chunks
```

### ES + Milvus 导入

```bash
# 1. 初始化索引
uv run python scripts/init_es.py
uv run python scripts/init_milvus.py

# 2. 导入 ES
uv run python scripts/import_es.py --dir ./chunks

# 3. 导入 Milvus (安全模式)
python scripts/import_milvus.py --dir ./chunks --mode single --device cuda:0

# 4. 或高效模式
python scripts/import_milvus.py --dir ./chunks --mode batch --device cuda:0
```

### 下载模型

```bash
uv run python scripts/download_model.py          # 默认镜像源
```

---

## 4. Chunk 三层结构

| Level | Chunk Type | 每篇数量 | 内容 |
|---|---|---|---|
| L0 | `paper` | 1 | 刊名/DOI/标题/摘要/关键词 |
| L1 | `paragraph` | ~18 | 章节坐标 + 正文段落 |
| L2 | `table` | ~3 | 章节坐标 + 作者结论 + HTML |

### Chunk 字段分库

| 字段 | L0 | L1 | L2 | Milvus | ES |
|---|---|---|---|---|---|
| `chunk_id` | ✓ | ✓ | ✓ | PK | keyword |
| `doc_id` | ✓ | ✓ | ✓ | 标量 | keyword |
| `doi` | ✓ | ✓ | ✓ | 标量 | keyword |
| `level` | ✓ | ✓ | ✓ | 标量 | keyword |
| `chunk_type` | ✓ | ✓ | ✓ | 标量 | keyword |
| `journal/section/article_type/title_cn` | ✓ | — | — | 标量 | keyword/text |
| `heading_stack/heading_depth` | — | ✓ | ✓ | — | keyword/short |
| `table_number/table_caption/html_size` | — | — | ✓ | — | short/text/int |
| `refers_to_tables` | — | ✓ | — | — | keyword[] |
| `content` | ✓ | ✓ | ✓ | →向量 | text (BM25) |
| `html_body` | — | — | ✓ | — | text (index:false) |

---

## 5. 检索流程

```
query
  │
  ├── Milvus 向量检索 (topK=200, COSINE)
  │     ← chunk_ids + score_m
  │
  ├── ES BM25 全文检索 (topK=200, ik_smart)
  │     ← chunk_ids + score_e
  │
  ▼
RRF 融合: score = 1/(60+rank_m) + 1/(60+rank_e)
  │
  ▼
ES mget → content + html_body
  │
  ▼
Rerank 精排 (预留接口)
  │
  ▼
LLM 回答
```

---

## 6. 每个文件的用途

### 核心源码 (`src/`)

| 文件 | 用途 |
|---|---|
| `config.py` | 全局配置 (PG/Redis/MinIO/MinerU/ES/Milvus) |
| `chunker.py` | 三粒度切分: full.md → L0/L1/L2 |
| `search.py` | 双路检索 + RRF + Rerank 接口 |
| `minio_client.py` | MinIO 四桶操作 (raw-docs/doc-meta/parsed-data/chunks) |

### 脚本 (`scripts/`)

| 文件 | 用途 |
|---|---|
| `run_chunker.py` | 批量切分 (断点续跑/失败隔离/原子写入/日志) |
| `download_model.py` | 下载 bge-m3 (多源降级: ModelScope/HF镜像/直连) |
| `init_es.py` | ES 索引初始化 (IK分词器 + 完整 mapping) |
| `init_milvus.py` | Milvus Collection 初始化 (标量 + 1024dim 向量) |
| `import_es.py` | 批量导入 chunks → ES (断点续跑/日志/幂等) |
| `import_milvus.py` | 批量导入 chunks → Milvus (single/batch 双模式) |
