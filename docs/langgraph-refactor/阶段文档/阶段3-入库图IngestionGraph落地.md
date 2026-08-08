# 阶段 3：入库图 IngestionGraph 落地

> 归属：`docs/langgraph-refactor/阶段文档/阶段3-入库图IngestionGraph落地.md`
> 总纲依据：`docs/langgraph-refactor/总需求文档.md`（重点 §6.1 通用约束 C1~C10、§6.2 入库图）

---

## 一、核心目标

阶段 3 把**文档入库管线**（上传 → MinerU 批提交 → 队列 → 轮询 → 下载解包 → 切分 → 嵌入 → ES/Milvus 双写 → READY）从 worker 隐式 while 轮询迁移为 **LangGraph 入库图**，兑现"队列无 ack、worker 崩溃丢批、索引无检查点、删除 key 错位"四大缺陷的修复。

1. **O-3.1 IngestionGraph 落地**：`poll→download→unpack→dispatch_index→(index_document 子图)→finalize` 节点 DAG；图成为 `pipeline_steps` 与 `document_tasks.status` 唯一写入方。
2. **O-3.2 独立 worker 进程**：删除 `lifespan` 内嵌 `run_worker_background`，worker 迁为独立进程/容器，消费可靠队列驱动图。
3. **O-3.3 checkpoint 断点续跑**：`langgraph-checkpoint-postgres` 装配；崩溃后从最后完成节点续跑，索引重入幂等。
4. **O-3.4 retry 改 checkpoint 恢复**：admin retry 不再按 `PIPELINE_STEPS_ORDER` 下标重置，改从 checkpoint 恢复；禁止复用已消费 batch_id。
5. **O-3.5 提交逻辑统一**：`SubmissionService` 收敛 `_submit_batches`（main 批量）与 `_submit_one_file`（admin 单文件）双入口，额度 `reserve/commit/refund` 三阶段接入。
6. **O-3.6 doc_id 统一与存量迁移**：冻结 `doc_id = article_id 兜底 md5[:8]`，存量 ES/Milvus 重刷补过滤字段；删除 key 统一 doc_id，修复在线文档删除残留。
7. **O-3.7 秒传/查重语义冻结**：KB 内查重，跨 KB 复制新 task 保留 parsed 引用，禁止 reassign kb_id 归属漂移。

---

## 二、开发范围（含边界）

### 2.1 包含（In Scope）

| 编号 | 工作项 | 说明 |
| --- | --- | --- |
| S-3.1 | IngestionGraph | `application/graphs/ingest_graph.py` + `state.py(IngestState)` + `nodes/{poll,download,unpack,dispatch_index,chunk,embed,es_write,milvus_write,finalize}.py` + `subgraphs/index_document.py` |
| S-3.2 | 独立 worker | `application/worker.py` 独立进程 driver（消费队列 → `graph.ainvoke`，可定时唤醒 resume）；删 lifespan 内嵌；Compose 服务占位（阶段 5 完善） |
| S-3.3 | checkpoint | `infrastructure/checkpoint/pg_saver.py`；`checkpoint_registry.py`（thread_id 分配/恢复） |
| S-3.4 | retry_service | retry 从 checkpoint 恢复；`RetryPolicy` 显式 `retry_on`（Transient）；`RecursionLimit` 保护 |
| S-3.5 | SubmissionService | 统一双提交入口；`reserve→commit→refund`；`MINERU_BATCH_SIZE` 分批；`429` 退避保留 |
| S-3.6 | 删除服务 | `DeleteDocumentService` 按统一 doc_id 从 ES delete_by_query + Milvus delete，先删后收尾，残留可对账 |
| S-3.7 | doc_id 存量迁移 | 一次性重刷脚本：重算 doc_id、补齐 Milvus 过滤字段（level/doi/chunk_type/journal/section/article_type/title_cn）、按新口径重建 chunk_id |
| S-3.8 | 秒传/查重 | `DocumentTaskRepositoryPort` 实现 KB 内查重；跨 KB 复制语义；禁止 reassign kb_id |
| S-3.9 | 队列接通 | 阶段 1 的 queue_adapter 与 worker driver 接通（claim→ack/nack），payload 存 token_id |

### 2.2 不包含（Out of Scope）

| 项 | 说明 |
| --- | --- |
| 不做 QAGraph | 阶段 4 |
| 不做前端 | — |
| 不做 metrics/trace | 阶段 5 |
| 不重构 chunker 算法 | 切分逻辑阶段 2 已归位，本阶段只编排 |

### 2.3 边界与约束

- 本阶段必须遵守总纲 §6.1 约束 **C3（compile 必挂 checkpointer）、C4（显式 retry_on）、C5（poll 无 sleep 状态机 + RecursionLimit）、C10（子图 thread 命名空间继承）**。
- 图是 `pipeline_steps/status` **唯一写入方**；worker driver 不得直接写库状态。
- Milvus 写入幂等（先删后插）是本阶段重入安全的前提，阶段 1 已建，此处接入节点。
- **任何"在途批"的并发双处理**（retry 与存活 worker 同时处理同一 batch）必须有锁/认领语义。

---

## 三、前置依赖

| 依赖 | 验收条件 |
| --- | --- |
| 阶段 0 | langgraph + langgraph-checkpoint-postgres 显式声明并落锁；checkpoint 表已建；pytest 全绿 |
| 阶段 1 | AppContainer、可靠队列（token_id）、额度三阶段、Milvus 幂等 upsert、事件总线 |
| 阶段 2 | 状态机、pipeline_steps 校验器、`chunk_document` 唯一切分入口、KBKind |
| `langgraph-checkpoint-postgres` 可运行 | `uv run python -c "from langgraph.checkpoint.postgres import AsyncPostgresSaver"` 通过 |

---

## 四、功能清单与数据契约

### 4.1 功能清单

| 编号 | 功能 | 产出 |
| --- | --- | --- |
| F-3.1 | 入库图 | `ingest_graph.py` + 节点 + `index_document` 子图 |
| F-3.2 | 独立 worker | `application/worker.py`（`python -m app.application.worker` 可独立启动） |
| F-3.3 | checkpoint 续跑 | `pg_saver.py` + `checkpoint_registry.py` |
| F-3.4 | checkpoint retry | `retry_service.py` |
| F-3.5 | 统一提交 | `document_submission.py` |
| F-3.6 | 删除服务 | `document_retrieval.py`/`DeleteDocumentService`（按 doc_id） |
| F-3.7 | 存量迁移 | `cli/migrate_doc_id.py`（一次性） |
| F-3.8 | 秒传语义 | repository 实现 |

### 4.2 数据契约（本阶段落地/变更）

**4.2.1 IngestState（图状态）**

```python
IngestState = {
  task_id: str, doc_id: str, md5: str, kb_id: int, kb_kind: KBKind,
  es_index: str, milvus_collection: str,
  batch: BatchMessage | None,                 # 见阶段1契约
  md5_to_item: dict[str, dict],
  pipeline_steps: PipelineSteps,              # 图是唯一写入方
  parsed: {parsed_dir, full_md, content_list_v2} | None,
  chunks: list[Chunk] | None, vectors: list[list[float]] | None,
  es_write: {written, index} | None, milvus_write: {written, collection} | None,
  poll_count: int, error: {step, type: Fatal|Transient, message} | None, fatal: bool,
}
```

**4.2.2 checkpoint thread_id**

- 批图 `thread_id = batch_id`；`index_document` 子图 `thread_id = task_id`（继承父图命名空间，避免多 thread 干扰）。
- 崩溃恢复：同一 `thread_id` 重 `ainvoke`，从最后完成节点续跑。

**4.2.3 秒传/查重语义（冻结）**

```
KB 内查重：同 KB 内按 md5 命中且 parsed 存在 → 秒传（直接复用 parsed 进索引）
跨 KB 重传：复制新 task，保留 parsed_minio_path 引用，允许重索引到新 KB 索引
禁止：reassign 已有 task 的 kb_id（杜绝归属漂移）
```

**4.2.4 删除 key 统一**

- 删除唯一依据 `doc_id`（不再取 `batch_id or md5`）；ES `delete_by_query(term: doc_id)` + Milvus `delete(doc_id=="...")`。
- 删除前校验 pipeline_steps 目标索引/集合，删除后校验残留=0（可对账）。

**4.2.5 RetryPolicy（红线 C4）**

```python
retry_on=lambda e: isinstance(e, MineruTransientError),  # 显式声明，绝不依赖默认
max_retries=3
# interrupt/暂停恢复依赖持久 checkpointer（红线 C3），任何裸 compile 禁止
```

### 4.3 本阶段变更点

- `admin retry` 端点：从"下标重置 PIPELINE_STEPS_ORDER"改为"checkpoint 恢复 + 必要时重新 submit（新 batch_id）"。
- `main.py`/`admin.py` 的上传提交逻辑收敛到 `SubmissionService`。
- worker 从 API 进程剥离（`lifespan` 不再 spawn）。
- 存量 ES/Milvus 数据按新 doc_id 口径与过滤字段重刷。

---

## 五、验收用例与自动化测试

### 5.1 验收用例（手动/端到端）

| 编号 | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A-3.1 | 全链路入库 | 上传 PDF → 等待 READY | 六步 pipeline_steps 全 done；ES/Milvus 可检索 |
| A-3.2 | 崩溃续跑（索引中） | 索引执行中 kill worker，重启 | 从最后完成节点续跑，不重复、不撞主键，最终 READY |
| A-3.3 | 崩溃续跑（轮询中） | MinerU 轮询中 kill worker，重启 | poll_count 从 checkpoint 续；未超 MAX_POLL_TIME 正常完成 |
| A-3.4 | 删除无残留 | 删除已入库文档 | ES/Milvus 按 doc_id 清理，残留计数=0 |
| A-3.5 | 秒传不串库 | 同 PDF 上传到 KB-A 后再上传到 KB-B | KB-A 秒传；KB-B 建新 task 独立索引；A 的 task.kb_id 不变 |
| A-3.6 | retry 从 checkpoint | 索引中失败，管理端 retry | 从失败节点续跑；不出现已消费 batch_id 重放 |
| A-3.7 | 双 worker 并发 | 起 2 个 worker 消费同一队列 | 同一批仅被一个 worker 处理（认领锁生效）；无重复索引 |
| A-3.8 | 存量迁移 | 对旧数据跑 migrate_doc_id | doc_id 统一、Milvus 过滤字段非空、删除可命中 |
| A-3.9 | 额度守恒 | 提交失败批次 | commit 前失败→refund；当日用量不虚高 |

### 5.2 自动化测试清单

| 编号 | 测试 | 类型 | 断言要点 |
| --- | --- | --- | --- |
| T-3.1 | `test_ingest_graph_happy_path` | 集成(全 fake + testcontainers) | 全节点推进，pipeline_steps 终态 READY，ES/Milvus 写入数与 chunk 数一致 |
| T-3.2 | `test_ingest_graph_checkpoint_resume` | 集成 | 中断注入后同 thread_id 续跑，幂等（ES `_id`/Milvus PK 不冲突） |
| T-3.3 | `test_poll_state_machine` | 单元 | poll_count 递增；超过 MAX_POLL_TIME 走 timeout 条件边→finalize FAILED |
| T-3.4 | `test_transient_retry` | 单元(InMemory saver) | 显式 retry_on 触发重试；Fatal 短路 finalize |
| T-3.5 | `test_no_checkpointer_is_redline` | 单元 | 裸 compile（无 saver）被检测/拒绝（架构红线 C3 静态守卫） |
| T-3.6 | `test_dedup_kb_scoped` | 集成 | 同 KB 秒传；跨 KB 新 task；kb_id 不变 |
| T-3.7 | `test_delete_by_doc_id` | 集成(testcontainers) | 删除后 ES 查询 0 命中、Milvus count=0 |
| T-3.8 | `test_retry_from_checkpoint` | 集成 | 失败后 retry 从失败节点恢复，不重放已提交步骤 |
| T-3.9 | `test_concurrent_claim` | 集成(fakeredis + 双消费者) | 可见性超时窗口内仅一消费者认领 |
| T-3.10 | `test_quota_commit_refund` | 集成 | 成功 commit、失败 refund、余额正确 |
| T-3.11 | `test_worker_standalone` | 进程 | `python -m app.application.worker` 可独立启动并消费 |
| T-3.12 | `test_migrate_doc_id` | 集成 | 迁移后 doc_id 口径统一、过滤字段非空 |

### 5.3 质量门槛

- 崩溃注入（A-3.2/A-3.3）通过，无重复脏数据。
- 删除残留=0（A-3.4 通过）。
- 双 worker 并发安全（A-3.7 通过）。
- `grep -rn "run_worker_background" src/` 无命中（worker 已剥离）。
- checkpoint 表、doc_id 迁移、删除 key 统一三项静态可查。
