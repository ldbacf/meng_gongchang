# Claude Code Context — MinerU Pipeline 阶段一

---

## 1. 当前流程

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  客户端   │────▶│ FastAPI  │────▶│ MinerU   │────▶│  Worker  │
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
```

### 步骤 1 — 文件上传 & MD5 查重

客户端 POST PDF 到 FastAPI `/api/v1/documents` 或 `scripts/scan_submit.py` 扫文件夹。

**三步验证防重：**
1. 计算文件 MD5 → 查 PostgreSQL `document_tasks` 表
2. 若 `status=parsed` → 调用 MinIO `stat_object` 确认 `parsed-data/{MD5}/full.md` 真实存在
3. 两步都满足 → **秒传**，直接返回解析结果路径；任一不满足 → **重新提交解析**

### 步骤 2 — 存原始 PDF & 写 DB

新文件的原始 PDF 存入 MinIO `raw-docs/{MD5}/{filename}`，JSON 元信息存入 `doc-meta/{MD5}/{filename}.json`，PostgreSQL 插入一条 `status=pending` 的记录。

### 步骤 3 — 提交 MinerU 解析

调用 MinerU `POST /api/v4/file-urls/batch` 获取预签名上传 URL → PUT 上传 PDF 到 OSS → 系统自动提交解析任务。返回的 `batch_id` 和对应 `md5_list` 推入 Redis 队列 `mineru:poll_queue`。DB 状态更新为 `processing`。

**多 Key 自动轮换（Best-fit 分配）：** 先读 PDF 页数 → `KeyManager.acquire(pages)` 在所有 key 中找剩余额度最接近但不浪费的那个 → 用该 token 上传。所有 key 额度用完时自动停止，第二天重跑自动续上。

**429 限流处理：** `_post` 中内置指数退避重试（2s → 4s → 8s，最多 3 次）。`scan_submit.py` 每批提交后等 2 秒再提交下一批，降低被限流概率。

### 步骤 4 — Worker 轮询 & 解包入库

后台 Worker 从 Redis BLPOP 取出 `batch_id` → 轮询 `GET /api/v4/extract-results/batch/{batch_id}` → 状态变为 `done` 后下载 ZIP → 内存解压：

- 正则替换 `full.md` 中图片路径 `images/xxx.jpg` → `http://localhost:9000/parsed-data/{MD5}/images/xxx.jpg`
- 全量写入 MinIO `parsed-data/{MD5}/`（含 full.md / middle.json / layout.json / 图片等）
- 更新 PostgreSQL `status=parsed`，记录 `parsed_minio_path`
- 如果 batch 404 或 token 失效 → 直接标记 failed（不等超时）

### 状态机

```
pending → processing → parsed
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
| 基础设施 | Docker (PostgreSQL + Redis + MinIO 全部容器化) |
| 数据持久化 | `./data/postgres/`, `./data/redis/`, `./data/minio/` 挂载到本地 |

### Docker 容器

| 服务 | 镜像 | 端口 |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | 5432 |
| Redis | `redis:7.4.8` | 6379 |
| MinIO | `cgr.dev/chainguard/minio:latest` | 9000 (API), 9001 (Console) |

### 目录结构

```
project/
├── after/                  # 测试用 PDF 文件 (3个中文/英文论文)
├── data/                   # Docker 数据卷持久化 (gitignore)
│   ├── postgres/
│   ├── redis/
│   └── minio/
├── ok/                     # test_mineru.py 输出目录 (gitignore)
├── src/                    # 阶段一主代码
│   ├── __init__.py
│   ├── config.py           # 全局配置
│   ├── db.py               # SQLAlchemy 异步引擎
│   ├── models.py           # ORM 模型 (DocumentTask)
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── key_manager.py      # 多 Token 额度管理器
│   ├── redis_client.py     # Redis 队列操作
│   ├── minio_client.py     # MinIO 四桶操作
│   ├── mineru_client.py    # MinerU API v4 客户端
│   ├── chunker.py          # 三粒度分层切分 (L0论文/L1章节/L2表格)
│   ├── worker.py           # 后台轮询 Worker
│   └── main.py             # FastAPI 应用
├── scripts/
│   ├── scan_submit.py      # 文件夹扫描提交器 (配对/去重/分配/提交)
│   └── run_chunker.py      # 批量切分脚本 (断点续跑/失败隔离/原子写入)
├── chunks/                 # chunk JSON 输出目录 (gitignore), MinIO chunks 桶镜像
├── test/
│   ├── test_mineru.py      # MinerU API 独立测试
│   ├── test_mineru_keys.py # Key 可用性测试
│   └── test_pipeline.py    # 阶段一端到端测试
├── docker-compose.yml      # Docker 编排文件
├── pyproject.toml          # uv 项目配置 & 依赖
├── .env / .env.example     # 环境变量
├── .gitignore
└── CLAUDE.md               # 本文件
```

### MinIO 四桶

| 桶名 | 用途 | 路径格式 |
|---|---|---|
| `raw-docs` | 原始 PDF 备份 | `{MD5}/{filename}` |
| `doc-meta` | PDF 对应元信息 JSON | `{MD5}/{filename}.json` |
| `parsed-data` | 解析产物 | `{MD5}/full.md`, `{MD5}/middle.json`, `{MD5}/layout.json`, `{MD5}/images/*` |
| `chunks` | 切分结果 JSON | `{uuid}.json` |

启动时 `init_buckets()` 会自动检查并创建不存在的桶。

---

## 3. 每个工具的用法

### 基础设施 (Docker)

```bash
# 启动所有服务 (PostgreSQL + Redis + MinIO)，后台运行
docker compose up -d

# 查看运行状态
docker compose ps

# 查看日志
docker compose logs -f           # 全部
docker compose logs -f postgres  # 单个服务

# 停止
docker compose down

# 停止并清除数据卷
docker compose down -v
```

### Python 依赖管理 (uv)

```bash
# 激活 conda 环境 (每次终端必须)
source D:/anaconda/Scripts/activate rag_test

# 安装/同步依赖
uv sync

# 添加新依赖
uv add <package-name>

# 运行 Python 脚本
uv run python <script.py>
```

### 启动 API 服务 (终端 2)

```bash
source D:/anaconda/Scripts/activate rag_test
cd /d/aaa_garbages/shangke/project/test
uv run uvicorn src.main:app --reload --port 8000
```

### 启动后台 Worker (终端 3)

```bash
source D:/anaconda/Scripts/activate rag_test
cd /d/aaa_garbages/shangke/project/test
uv run python -m src.worker
```

### 文件夹扫描提交 (主力工具)

```bash
# 扫描目录下 pdf/ + json/ 配对，去重后提交
uv run python scripts/scan_submit.py --dir ./my_data

# 只看统计，不提交
uv run python scripts/scan_submit.py --dir ./my_data --dry-run

# 只看页数统计
uv run python scripts/scan_submit.py --dir ./my_data --pages-only
```

自动识别两种目录结构:
```
# 子目录模式（推荐）
my_data/
  pdf/xxx.pdf
  json/xxx.json

# 平铺模式（PDF 和 JSON 混放）
my_data/
  xxx.pdf
  xxx.json
```

自动记录日志到 `log/scan_{时间戳}.log`。每批提交后等 2 秒减缓限流。结束时显示准确的成功/失败统计。

> 注意：`scan_submit.py` 使用 `--dir` 参数指定数据目录。`.env` 中的 `PDF_INPUT_DIR` 是给 `test/test_pipeline.py` 和 `test/test_mineru.py` 用的，两者不冲突。

### 三粒度分层切分 (Chunker)

```bash
# 切分全库（断点续跑，自动跳过已完成文档）
uv run python scripts/run_chunker.py --out-dir ./chunks

# 测试 N 篇
uv run python scripts/run_chunker.py --limit 20 --out-dir ./chunks

# 指定 MD5
uv run python scripts/run_chunker.py --md5 abc123,def456 --out-dir ./chunks

# 禁用断点续跑（从头处理）
uv run python scripts/run_chunker.py --no-resume --out-dir ./chunks

# 切分完成后上传全部 JSON 到 MinIO chunks 桶
uv run python scripts/run_chunker.py --upload --out-dir ./chunks

# 只上传本地已有 JSON（不重新切分）
uv run python scripts/run_chunker.py --upload-only --out-dir ./chunks
```

**输出**：`chunks/{uuid}.json`（UUID 与 MinIO 内 `{uuid}_content_list_v2.json` 一致，可直接回溯源文件），每篇 PDF 一个 JSON，内含三层 chunk：

| Level | Chunk Type | 每篇数量 | 内容 |
|---|---|---|---|
| L0 | `paper` | 1 | 刊名/DOI/标题/摘要/关键词 ← **论文发现** |
| L1 | `paragraph` | ~18 | 章节坐标 + 正文段落 ← **语义检索** |
| L2 | `table` | ~3 | 章节坐标 + 作者结论 + 表注 + HTML源码 ← **数据检索** |

**切分逻辑**（详见 `src/chunker.py`）：
1. 从 `full.md` 解析标题、段落、表格（HTML）、表注
2. 按编号点号深度构建标题栈（`1`→L1, `1.1`→L2, `1.1.1`→L3）
3. 扫描段落中的表号引用（`见表X`），建立段落→表格的灵魂池
4. 从 `content_list_v2.json` 回填更完整的 `table_footnote`（术语缩写解释）
5. 组装三层 chunk：HTML 不进向量（存 `html_body`），embedding 只吃标题栈+结论+caption+footnote

**健壮性**：
- 断点续跑：`chunks/.checkpoint.json` 记录已完成 MD5
- 单条失败隔离：异常不中断整体，错误记入 `log/chunker_{timestamp}.log`
- MinIO 重试：每个数据源 3 次指数退避
- 原子写入：先写 `.tmp` 再 rename

**Chunk 字段速查**：

| 字段 | L0 | L1 | L2 | 存 Milvus | 存 ES |
|---|---|---|---|---|---|
| `chunk_id` | ✓ | ✓ | ✓ | 主键 | 主键 |
| `doc_id` / `doi` | ✓ | ✓ | ✓ | 标量 | keyword |
| `level` / `chunk_type` | ✓ | ✓ | ✓ | 标量 | keyword |
| `journal` / `source` / `section` / `article_type` | ✓ | — | — | — | keyword |
| `title_cn` / `keywords_cn` | ✓ | — | — | — | keyword |
| `heading_stack` / `heading_depth` | — | ✓ | ✓ | — | keyword |
| `table_number` / `table_caption` / `html_size` | — | — | ✓ | — | integer/text |
| `refers_to_tables` | — | ✓ | — | — | keyword[] |
| `content` | ✓ | ✓ | ✓ | **→向量** | text (BM25) |
| `html_body` | — | — | ✓ | — | text (不分词) |

### MinerU API 独立测试

```bash
# 单文件
uv run python test/test_mineru.py -f "after/xxx.pdf"

# 批量 (扫描 after/ 下所有 PDF)
uv run python test/test_mineru.py --batch

# URL 模式
uv run python test/test_mineru.py -u "https://example.com/doc.pdf"
```

### Key 可用性测试

```bash
uv run python test/test_mineru_keys.py
```

### 阶段一管线端到端测试

```bash
# 单文件
uv run python test/test_pipeline.py -f "after/xxx.pdf"

# 批量
uv run python test/test_pipeline.py --batch
```

### API 手动调用 (curl)

```bash
# 上传单文件
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@after/xxx.pdf"

# 批量上传
curl -X POST http://localhost:8000/api/v1/documents/batch \
  -F "files=@after/a.pdf" \
  -F "files=@after/b.pdf"

# 查状态 (按 ID / MD5)
curl http://localhost:8000/api/v1/documents/<uuid>
curl http://localhost:8000/api/v1/documents/md5/<md5>

# 健康检查
curl http://localhost:8000/health

# 查看 Token 当日用量
curl http://localhost:8000/api/v1/tokens/usage
```

---

## 4. 操作流程

### 首次部署

```bash
# 1. 克隆项目，进入目录
cd /d/aaa_garbages/shangke/project/test

# 2. 激活 conda 环境
source D:/anaconda/Scripts/activate rag_test

# 3. 安装依赖
uv sync

# 4. 配置 .env（Token、密钥等）
#    编辑 .env 填入 MINERU_TOKENS（多个用逗号分隔）

# 5. 启动基础设施
docker compose up -d

# 6. 启动 Worker（终端 1）
uv run python -m src.worker

# 7. 启动 API（终端 2，可选，走 FastAPI 时需要）
uv run uvicorn src.main:app --reload --port 8000
```

### 每日操作

```bash
# 1. 确保基础设施在运行
docker compose ps

# 2. 确保 Worker 在运行（终端 1）
uv run python -m src.worker

# 3. 执行扫描提交
uv run python scripts/scan_submit.py --dir D:/my_data
```

首次会自动建表、建桶、加载 KeyManager。后续重复执行会自动跳过已完成的文件。

### 断点续跑

中断后重新执行即可，不会重复提交：

```bash
uv run python scripts/scan_submit.py --dir D:/my_data
```

自动跳过 `parsed` / `processing` 的文件，只提交 `failed` / `pending` / 新文件。

### Token 额度用尽后

第 2 天 Worker 继续跑完前一天的任务。重新执行 `scan_submit.py`：

- 已完成 → 跳过
- 额度用完失败的 → 自动重试（额度已重置）

### 监控

```bash
# 查看解析状态（DB + MinIO 双验证）
uv run python scripts/check_status.py --detail

# 列出桶中文件夹数量
uv run python scripts/list_bucket.py                    # parsed-data
uv run python scripts/list_bucket.py --all              # 四桶
uv run python scripts/list_bucket.py --bucket raw-docs  # 指定桶

# 查看 Token 当日余额
curl http://localhost:8000/api/v1/tokens/usage

# 查看 Worker 日志
# 切换到 Worker 终端即可看到实时日志

# 查看 Docker 服务状态
docker compose logs -f
```

### 测试

```bash
# Key 是否可用
uv run python test/test_mineru_keys.py

# 端到端管线测试（需要 FastAPI 运行中）
uv run python test/test_pipeline.py --batch
```

---

## 5. 每个工具的用途

| 工具 | 用途 |
|---|---|
| **Docker** | 运行全部基础设施 (PG/Redis/MinIO)，避免本地安装差异 |
| **PostgreSQL 16** | 业务账本 — 记录每份文档的 MD5、状态、MinIO 路径；MD5 唯一索引实现防重 |
| **Redis 7.4** | 轻量任务队列 — 存储待轮询的 `batch_id`，Worker 通过 BLPOP 阻塞消费 |
| **MinIO (chainguard)** | S3 兼容对象存储 — `raw-docs` 存原始 PDF，`doc-meta` 存元信息 JSON，`parsed-data` 存解析产物；通过 MD5 实现物理目录隔离 |
| **FastAPI** | 对外网关 — 接收文件上传、MD5 计算、业务调度 |
| **Uvicorn** | ASGI 服务器，运行 FastAPI 应用 |
| **SQLAlchemy 2.0 (async)** | 异步 ORM — 配合 asyncpg 驱动操作 PostgreSQL |
| **httpx (async)** | 全异步 HTTP 客户端 — 调用 MinerU API，设置 `proxy=None` + `trust_env=False` + `http2=False` 绕过系统代理 |
| **PyMuPDF (fitz)** | 读 PDF 页数，不依赖其他 PDF 工具 |
| **tqdm** | 进度条 — 扫码、提交、切分时显示进度 + 当前MD5 + chunk数 |
| **logging** | 结构化日志 — 双输出：控制台 INFO（tqdm.write）+ 文件 DEBUG（traceback） |
| **uv** | Python 包管理器 — 管理依赖、虚拟环境、脚本运行 |
| **MinerU API v4** | 第三方文档解析云服务 — 将 PDF 解析为 Markdown + JSON + 图片的 ZIP 包 |

### MinerU API 关键端点

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/v4/file-urls/batch` | POST | 申请批量上传预签名 URL |
| (预签名 URL) | PUT | 上传 PDF 到 OSS（不设 Content-Type） |
| `/api/v4/extract-results/batch/{batch_id}` | GET | 批量查询解析进度 |
| `/api/v4/extract/task` | POST | 单文件 URL 直接解析 (跳过上传) |
| `/api/v4/extract/task/{task_id}` | GET | 单文件查询解析进度 |
| `/api/v4/extract/task/batch` | POST | 批量 URL 解析 | |

---

## 6. 每个文件的用途

### 配置文件

| 文件 | 用途 |
|---|---|
| `pyproject.toml` | uv 项目元数据 — 依赖声明、build 配置 (hatchling)、CLI 入口 |
| `.env` | 实际环境变量 — 数据库密码/MinIO 密钥/MinerU Token (不提交 git) |
| `.env.example` | 环境变量模板 — 含中文注释说明每个变量含义 (可提交 git) |
| `.gitignore` | 忽略 .env / .venv / data / ok / __pycache__ 等 |
| `docker-compose.yml` | Docker 服务编排 — 定义 PG/Redis/MinIO 的镜像、端口、健康检查、数据卷挂载 |

### 核心源码 (`src/`)

| 文件 | 用途 |
|---|---|
| `src/__init__.py` | 包标记 |
| `src/config.py` | 全局配置中心 — 从 .env 读取所有环境变量并转为 Python 常量；含四桶名（`raw-docs`/`doc-meta`/`parsed-data`/`chunks`） |
| `src/db.py` | 异步 SQLAlchemy 引擎 & session 工厂 |
| `src/models.py` | ORM 模型 `DocumentTask` — 字段: id/md5/original_name/raw_minio_path/meta_minio_path/parsed_minio_path/status/batch_id/error_msg |
| `src/schemas.py` | Pydantic 模型 — `TaskCreateResponse` / `TaskStatusResponse` |
| `src/key_manager.py` | 多 Token 额度管理器（Best-fit 分配） — `acquire(pages)` 找剩余最接近的 key，`release()` 扣除额度，`usage_report()` 查看用量，每日自动重置 |
| `src/redis_client.py` | Redis 队列 — `enqueue_batch(batch_id, md5_list, token)` / `dequeue_batch()` |
| `src/minio_client.py` | MinIO 四桶操作 — `init_buckets()` / `upload_raw_pdf()` / `upload_meta_json()` / `upload_parsed_assets()`(图片路径替换) / `check_parsed_exists()` / `upload_chunk_json()` / `chunk_json_exists()` |
| `src/mineru_client.py` | MinerU API v4 客户端 — `submit_batch(file_infos, token)` / `poll_batch(batch_id, token)` / `download_result()` |
| `src/chunker.py` | 三粒度分层切分模块 — 解析 full.md（状态机）→ 提取表格/标题/段落 → 构建表格字典（跳过标题-HTML间杂物）→ 扫描段落表号引用（灵魂池）→ 回填 footnote（content_list_v2）→ 组装 L0/L1/L2 chunk；空 HTML / 缺 `<tr>` 输出 WARNING（含 doc_id + md5 + title_cn） |
| `src/worker.py` | 后台轮询 Worker — 阻塞监听 Redis → 轮询 MinerU → 下载 ZIP → 入库 → 更新 DB；遇到 batch 404 直接标记 failed |
| `src/main.py` | FastAPI 网关 — 上传/查询端点；`_handle_one_file()` 三步验证防重 + JSON 联带上传 |

### 脚本 (`scripts/`)

| 文件 | 用途 |
|---|---|
| `scripts/scan_submit.py` | 文件夹扫描提交器 — 扫描 `pdf/` + `json/` 配对 → MD5 查重 → 读页数 → KeyManager Best-fit 分配 → 每批 10 个提交（批间等 2s） → 429 指数退避重试 → 日志到 `log/` → 准确统计成功/失败数 |
| `scripts/run_chunker.py` | 批量切分 + 上传脚本 — 从 MinIO 拉取 full.md + content_list_v2 + doc-meta → 调用 chunker → 原子写 `{uuid}.json`；支持断点续跑 / 两阶段执行（`--upload` 先切后传、`--upload-only` 只传不切）/ 上传幂等（MinIO 已有则跳过）/ 独立进度条与日志 |
| `scripts/check_status.py` | 双验证状态检查 — DB 状态统计 + 逐文件验证 MinIO `parsed-data/{md5}/full.md` 是否存在 |
| `scripts/list_bucket.py` | MinIO 桶文件夹列表 — 列出桶中顶层文件夹，不递归 |

### 测试 (`test/`)

| 文件 | 用途 |
|---|---|
| `test/test_mineru.py` | MinerU API 独立测试 — 不依赖 Docker，直接调用 MinerU API 解析 PDF 并输出到本地 `ok/`。四种模式: 单文件/批量本地/单 URL/批量 URL |
| `test/test_mineru_keys.py` | Key 可用性测试 — 验证每个 Token 是否能正常调用 MinerU 接口，检测额度是否用完 |
| `test/test_pipeline.py` | 阶段一端到端测试 — 连接 FastAPI 验证完整链路 |

### 数据目录

| 路径 | 用途 |
|---|---|
| `after/` | 测试用 PDF 文件 (3个中英文论文 PDF) |
| `data/postgres/` | PostgreSQL 数据持久化 (gitignore) |
| `data/redis/` | Redis RDB/AOF 持久化 (gitignore) |
| `data/minio/` | MinIO 对象数据持久化 (gitignore) |
| `ok/` | `test_mineru.py` 的本地输出目录 (gitignore) |
| `chunks/` | Chunker 输出目录 — `{uuid}.json` + `.checkpoint.json` (gitignore) |
| `log/` | `scan_submit.py` + `run_chunker.py` 运行日志 (gitignore) |
