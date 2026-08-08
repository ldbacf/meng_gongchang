# 阶段 1：基础设施归位与 DI 容器

> 归属：`docs/langgraph-refactor/阶段文档/阶段1-基础设施归位与DI容器.md`
> 总纲依据：`docs/langgraph-refactor/总需求文档.md`

---

## 一、核心目标

阶段 1 把**基础设施层**收敛为可注入、可销毁、可替换的形态，是本阶段重构最大的去耦合动作。**本阶段不改变业务逻辑**，只改变客户端生命周期管理与 import 路径，功能回归通过即可。

1. **O-1.1 消灭模块级可变全局单例**：`_ES_CLIENT / _MILVUS_CONNECTED / _EMBED_MODEL / _manager(key) / _pool(redis) / get_minio` 全部收敛进 `AppContainer`，由容器统一 lazy 创建 + `async start/close` 销毁。
2. **O-1.2 单一工厂 / 双轨合一**：ES mapping 与 Milvus schema 从 `init_es.py`/`init_milvus.py` 抽为共享常量，在线自动建与规范脚本同源，杜绝双轨；bge-m3 多份单例收敛为唯一工厂。
3. **O-1.3 队列 at-least-once**：Redis List `BRPOP` 升级为 **Redis Streams + 消费者组**（`XADD`/`XREADGROUP`/`XACK` + pending 可见性超时 + DLQ），实现 `enqueue/claim/ack/nack/dead_letter` 语义，崩溃不丢批、多 worker 安全。
4. **O-1.4 额度 Redis 持久化**：KeyManager 内存态改 Redis 原子记账，语义修正为 `reserve → commit → refund` 三阶段，跨进程一致。
5. **O-1.5 事件总线**：`ws_manager` 全局单例改为 Redis Pub/Sub 事件总线（worker 发、ws 层订阅），消除跨进程广播丢失。
6. **O-1.6 Milvus 写入幂等**：按 `chunk_id` 先删后插/upsert，为阶段 3 图重跑提供安全前提。

---

## 二、开发范围（含边界）

### 2.1 包含（In Scope）

| 编号 | 工作项 | 说明 |
| --- | --- | --- |
| S-1.1 | AppContainer | `infrastructure/container.py`：lazy 单例 + `async start()/close()`，统一 dispose（engine/redis pool/milvus disconnect/bge-m3 释放）；`interface/deps.py` 提供 `get_container()` |
| S-1.2 | 客户端适配器 | `infrastructure/adapters/` 收敛 ES（带 request_timeout/auth/重连）、Milvus（连接+collection 单例+健康检查）、MinIO、MinerU（结构化 Fatal/Transient 异常）、Embedding（唯一工厂+批量 encode）、LLM Chat、Rerank |
| S-1.3 | 共享 schema 常量 | `infrastructure/es/es_mappings.py` + `milvus/schema.py`：mapping（init_es 完整 ik_smart `dynamic:strict` 30+ 字段）与 schema（10 字段 + dim=1024/COSINE/nlist）作为唯一来源；`EMBEDDING_DIM/MILVUS_NLIST` 入 Settings |
| S-1.4 | 可靠队列 | `infrastructure/redis/queue_adapter.py`：`enqueue/claim/ack/nack_requeue/dead_letter` + 可见性超时；payload 改 `token_id` 不含明文 token |
| S-1.5 | 额度记账 | `infrastructure/redis/quota_store_redis.py`：`quota:{key_id}:{date}` 原子 INCR/DECR；`reserve/commit/refund/balance` |
| S-1.6 | 事件总线 | `infrastructure/redis/event_bus_redis.py`：`publish/subscribe` 按 topic（kb_id）Pub/Sub |
| S-1.7 | import 路径迁移 | 现有 `src/*.py` 仅改 import（从 `app.infrastructure...` 取客户端），业务逻辑不动；`worker.py` 的 ws 广播改经事件总线 |
| S-1.8 | Milvus 幂等写入 | `milvus/repo.py.upsert_batch`：按 chunk_id 先删后插；`es/repo.py.bulk_write`：`_id=chunk_id` |

### 2.2 不包含（Out of Scope）

| 项 | 说明 |
| --- | --- |
| 不做领域层提取 | 聚合根/状态机/pipeline_steps 类型化在阶段 2 |
| 不建 LangGraph 图 | 阶段 3/4 |
| 不做 doc_id 统一迁移 | 阶段 3 |
| 不改前端 | — |
| 不重构业务编排 | 上传/检索/回答的编排逻辑本阶段原样保留 |

### 2.3 边界与约束

- 本阶段验收以"**26 模块仅改 import 路径，功能回归通过**"为准；任何业务行为变更视为范围蔓延。
- 容器实例必须可注入 fake（单测替换真实客户端），这是后续所有可测试性的前提。
- 队列 payload 自本阶段起禁止存放明文 MinerU token。

---

## 三、前置依赖

| 依赖 | 验收条件 |
| --- | --- |
| 阶段 0 完成 | Alembic 基线可用、Settings 单一真相源、pytest 全绿 |
| langgraph 依赖锁定 | `uv.lock` 含 `langgraph`、`langgraph-checkpoint-postgres`（阶段 0 已声明） |
| 基础设施运行 | docker-compose 8 服务健康 |

---

## 四、功能清单与数据契约

### 4.1 功能清单

| 编号 | 功能 | 产出 |
| --- | --- | --- |
| F-1.1 | AppContainer | `container.py`；`start/close` 幂等；容器单例工厂（get_es/get_milvus/get_redis/get_minio/get_embedder/get_llm/get_reranker/get_key_budget） |
| F-1.2 | 客户端适配器 | `adapters/{elasticsearch_,milvus,minio,mineru,embedding,llm_chat,rerank}.py` |
| F-1.3 | 共享 schema | `es/es_mappings.py` + `milvus/schema.py` + Settings 常量 |
| F-1.4 | 可靠队列 | `queue_adapter.py`（at-least-once） |
| F-1.5 | 额度记账 | `quota_store_redis.py` |
| F-1.6 | 事件总线 | `event_bus_redis.py` |
| F-1.7 | 模块 import 迁移 | 全部 `src/*.py` 改经容器/适配器取客户端 |

### 4.2 数据契约（本阶段新增/变更）

**4.2.1 队列消息（token 脱敏）**

```jsonc
BatchMessage { "batch_id": "…", "md5_list": ["…"], "token_id": "tk_1",
               "submit_ts": 1786000000.0, "attempts": 0 }
// token 明文字段废弃；token_id ↔ 密钥映射仅在 vault/container 内解析
```

**4.2.2 额度记账**

```text
Redis Key:  quota:{key_id}:{date}        → 已用页数（整数，原子 INCR/DECR）
            reservation:{task_id}        → {key_id, pages, state: reserved|committed|refunded}
语义：reserve(预占) → commit(仅 MinerU 提交成功) → refund(失败退回)
```

**4.2.3 事件总线**

```jsonc
// topic = kb_id；事件类型
{"type":"doc_update",  "doc": DocumentResponse}
{"type":"doc_deleted", "doc_id":"…"}
{"type":"step",        "step":"chunking", "status":"done", "count":128}   // 供阶段3图节点投影
```

**4.2.4 ES/Milvus schema 单源**

- `ES_MAPPINGS`（ik_smart、`dynamic:strict`、30+ 字段）与 `MILVUS_SCHEMA`（chunk_id PK / doc_id / doi / level / chunk_type / journal / section / article_type / title_cn / embedding[1024]）作为唯一常量；`init_es/init_milvus` 脚本与在线自动建共用。

### 4.3 本阶段变更点

- 所有 `src/*.py` 的客户端获取方式从模块级 global 改为容器注入。
- `worker.py` 的 `ws_manager.broadcast` 改为 `event_bus.publish`。
- MinerU 客户端抛结构化异常（`MineruFatalError`/`MineruTransientError`），替代字符串匹配（错误分类迁移在阶段 3 正式落地，本阶段先引入异常类型）。

---

## 五、验收用例与自动化测试

### 5.1 验收用例（手动/端到端）

| 编号 | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A-1.1 | 全功能回归 | 新架构下完整走一遍 上传→解析→索引→检索→回答 | 与旧版行为等价；全部步骤 done |
| A-1.2 | 双 worker 额度一致 | 起 2 个进程各提交任务 | 额度按 key+date 原子累加，无互相覆盖；重启后额度保留 |
| A-1.3 | kill worker 不丢批 | 任务提交后 kill worker，重启 | 该批从 processing list 经可见性超时恢复处理，不永久丢失 |
| A-1.4 | 容器关闭释放 | 正常 shutdown | engine.dispose/redis pool 断开/milvus 断开无泄漏日志 |
| A-1.5 | Milvus 幂等重跑 | 同一文档重复索引两次 | 不撞主键；第二次覆盖写入 |
| A-1.6 | 事件总线广播 | worker 触发索引步骤，前端 WS 订阅 | 跨进程也能收到 doc_update |

### 5.2 自动化测试清单

| 编号 | 测试 | 类型 | 断言要点 |
| --- | --- | --- | --- |
| T-1.1 | `test_container_lifecycle` | 单元(InMemory fake) | start/close 幂等；close 后连接释放回调被调用 |
| T-1.2 | `test_container_injectable` | 单元 | 容器可注入 fake ES/Milvus/Redis，业务调用打到 fake |
| T-1.3 | `test_es_mapping_single_source` | 单元 | init_es 用的 mapping 与在线建索引用的常量是同一对象 |
| T-1.4 | `test_milvus_schema_single_source` | 单元 | init_milvus 与在线建 collection 用同一 schema；dim/nlist 读 Settings |
| T-1.5 | `test_queue_at_least_once` | 集成(fakeredis 或 testcontainers Redis) | claim 后未 ack，可见性超时后回到 pending；ack 后不再重投；超限进 DLQ |
| T-1.6 | `test_queue_payload_no_token` | 单元 | BatchMessage 序列化不含明文 token，仅 token_id |
| T-1.7 | `test_quota_reserve_commit_refund` | 集成(fakeredis) | reserve 预占→commit 扣额；reserve→refund 退回；跨"进程"（两个 Redis 客户端）一致 |
| T-1.8 | `test_quota_daily_reset` | 集成 | 跨日期自动重置（注入 ClockPort） |
| T-1.9 | `test_event_bus_roundtrip` | 集成(fakeredis) | publish→subscribe 收到 doc_update/doc_deleted |
| T-1.10 | `test_milvus_upsert_idempotent` | 集成(testcontainers Milvus) | 同 chunk_id 二次 upsert 不撞主键、计数正确 |
| T-1.11 | `test_mineru_structured_errors` | 单元(mock httpx) | 429 重试后仍失败抛 MineruTransientError；致命文案抛 MineruFatalError |
| T-1.12 | `test_module_import_no_global` | 静态 | `grep` 无模块级 `global _ES_CLIENT/_MILVUS_CONNECTED/_EMBED_MODEL` |

### 5.3 质量门槛

- `uv run pytest` 全绿。
- 功能回归通过（A-1.1）。
- `grep -rn "global _ES_CLIENT" src/` 无命中；`src/*.py` 无 `os.getenv` 重复解析。
