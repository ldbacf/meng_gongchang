# LangGraph 双图设计（Mermaid）

> 与 `总需求文档.md` §6.2 / §6.3 对应。GitHub、VS Code（Mermaid Preview）、Typora 均可直接渲染 ```mermaid 块。

---

## 1. 入库图 IngestionGraph

**线程**：`thread_id = batch_id`（批图）/ `task_id`（`index_document` 子图）
**checkpoint**：`langgraph-checkpoint-postgres`，每节点边界写 `pipeline_steps`（图是唯一写入方）
**红线**：compile 必挂 checkpointer；RetryPolicy 显式 `retry_on`；poll 用 `poll_count` 状态机走条件边（LangGraph 无原生 sleep）

```mermaid
flowchart TD
    subgraph API["接口 / 应用层（API 进程）"]
        UP["POST /api/v1/documents 上传收单"]
        DS["document_service<br/>md5 查重 / 秒传判定 / 建 DocumentTask"]
        SUB["SubmissionService<br/>reserve→commit→refund 额度三阶段<br/>MinerU 批提交 → enqueue"]
    end

    subgraph QUEUE["可靠队列（Redis Streams · at-least-once）"]
        Q["BatchMessage(batch_id, md5_list, token_id, submit_ts, attempts)"]
    end

    subgraph WORKER["入库图 IngestionGraph（独立 worker 进程）"]
        direction TB
        POLL["poll_parsed<br/>发起 / 推进 MinerU 轮询<br/>poll_count + 1（≤ MAX_POLL_TIME）"]
        DL["download_assets<br/>下载解析 zip"]
        UN["unpack_store<br/>解包 + 改写图片 URL → parsed-data/(md5)/"]
        DI["dispatch_index<br/>遍历 md5_set，逐文档启动/续跑子图"]

        subgraph IDX["index_document 子图（thread_id = task_id）"]
            direction TB
            RD["read_markdown"]
            PM["parse_md<br/>FullMdParser 状态机"]
            CK["chunk_document<br/>L0 / L1 / L2 唯一切分入口"]
            EB["embed_batch<br/>bge-m3 encode(list) 批量编码"]
            EW["es_write<br/>bulk · _id = chunk_id"]
            MW["milvus_write<br/>按 chunk_id 先删后插（幂等 upsert）"]
            RD --> PM --> CK --> EB --> EW --> MW
        end

        FIN["finalize<br/>全 READY→READY / 任一 failed→FAILED<br/>WS doc_update + pipeline_steps 终态"]
    end

    UP --> DS --> SUB --> Q
    Q -->|"claim + ack"| POLL
    POLL -->|"done"| DL
    POLL -->|"pending → checkpoint 暂停<br/>scheduler TTL 唤醒回到自身"| POLL
    POLL -->|"failed / timeout"| COND{"fatal_or_retry"}
    COND -->|"retryable → requeue 重置该批"| Q
    COND -->|"非 retryable"| FIN
    DL --> UN --> DI
    DI -->|"逐 doc"| IDX
    IDX --> FIN
```

### 节点与条件边说明

| 节点 / 边 | 说明 |
| --- | --- |
| `poll_parsed` | 发起/推进 MinerU `extract-results` 轮询；`pending` 时经 checkpoint 暂停，由外部 scheduler 定时唤醒 resume（**不做节点内 while**）；`poll_count` 受 `MAX_POLL_TIME` 上限，配 `RecursionLimit` 防自环失控 |
| `fatal_or_retry` 条件边 | 依据错误类型分流：`Transient`（可重试）→ requeue 回队列重置该批；`Fatal` / 超时 → finalize 置 FAILED |
| `index_document` 子图 | 批内逐 doc 串行；子图内任一步抛 `Transient` → 节点级 `max_retries` 自环重试（显式 `retry_on`）；抛 `Fatal` → 短路 finalize |
| `es_write` / `milvus_write` | `_id` / 主键统一 `chunk_id`，重入幂等；Milvus 先删后插 |
| `finalize` | 汇总批结果：全部 READY → `status=READY`；任一失败 → `FAILED` + 事件总线广播 doc_update |

---

## 2. 问答图 QAGraph

**线程**：`thread_id = conversation_id:message_id`
**checkpoint**：节点边界落库（方案①）；token 级流式内容**不进 state**，避免高频序列化
**流式**：`stream_mode=['updates','values']` 产 `t:step`；`astream_events(v2)` + `adispatch_custom_event('token')` 产 `t:text`；心跳帧由独立 asyncio task 定时写队列

```mermaid
flowchart TD
    subgraph API["接口层"]
        ENTRY["POST /api/v1/chat/stream<br/>鉴权 + kb_id 归属校验<br/>落库用户消息 / 取会话 → message_id"]
    end

    subgraph RAG["问答图 QAGraph（application 层）"]
        direction TB
        BC["build_context<br/>历史窗口：回答 10 turns / 意图 2 turns<br/>KB 目标解析 + KBKind 策略"]
        INT["analyze_intent<br/>Medical / Generic 策略<br/>查询重写 + 指代消解<br/>失败 → 原 query 直通 + degraded"]
        EXP["expand_query<br/>口语 → 学术术语（条件节点）"]
        RET["dual_recall<br/>ES BM25 + Milvus COSINE 双路并行<br/>短 query（15 字以内）重复嵌入增强"]
        RRF["rrf_fusion<br/>k=20 按 chunk_id 去重<br/>ES 富字段回填"]
        RER["rerank<br/>Qwen3-Reranker-4B<br/>失败 → 保序返回 + degraded（不中断）"]
        CIT["build_citations<br/>按 doc_id 去重取前 5<br/>L0 回填 title_cn / journal<br/>snippet 200 字 → SSE t:cite"]
        ANS["generate_answer<br/>DeepSeek 流式<br/>token → SSE t:text"]
        PER["persist_message<br/>落库 AI 消息 + citations + rag_steps<br/>产 t:done + message_id"]
        ERR["error_handler<br/>产 t:error(code, message, retryable)<br/>落库 failed 的 AI 消息"]
    end

    ENTRY --> BC --> INT
    INT -->|"USE_QUERY_EXPANSION = true"| EXP
    INT -->|"否则跳过"| RET
    EXP --> RET
    RET --> RRF --> RER --> CIT --> ANS --> PER
    ANS -->|"LLM 流中断 → 从 rerank 重跑一次（checkpoint 续跑）"| RER
    RER -.->|"降级标记 degraded（数据仍在 state）"| CIT
    INT -.->|"意图失败降级：原 query 直搜"| RET
    RET -.->|"检索异常"| ERR
    ANS -.->|"仍失败"| ERR
    ERR --> PER
    PER --> DONE["END"]
```

### 节点与条件边说明

| 节点 / 边 | 说明 |
| --- | --- |
| `build_context` | 提取历史窗口（回答取最近 10 turns、意图取 2 turns），解析 KB 目标（es_index / milvus_collection / kb_kind） |
| `analyze_intent` | 按 `KBKind` 选 Medical / Generic 策略；重写 + 指代消解；失败降级为原 query 且 `metrics.intent.degraded = true` |
| `expand_query` | 仅 `USE_QUERY_EXPANSION` 且命中转换规则时执行（条件边） |
| `dual_recall` | `embed_query` 为并行前驱；ES bool（must content + should title_cn/keywords boost） + Milvus COSINE(nprobe=16)；初召各 topK=200 |
| `rrf_fusion` | RRF k=20 按 chunk_id 去重，回填 ES 富字段 → `SearchHit` 列表 |
| `rerank` | 失败返回原序并记 `metrics.rerank.degraded=true`（**不静默、不中断流**） |
| `build_citations` | 按 doc_id 去重取前 5，L0 回填标题/刊名，snippet 200 字 → 产 `t:cite` |
| `generate_answer` | DeepSeek 流式；token 经 `on_token` 回调泵入 asyncio.Queue → SSE `t:text`（沿用 ≥20 字符/标点拼批启发式） |
| `persist_message` | 落库 AI 消息 + citations + rag_steps，更新会话 updated_at；产 `t:done` 携带 message_id 供前端幂等 |
| `error_handler` | 任意节点致命异常 → 产 `t:error{code, message, retryable}` + 落库 failed 标记；**错误不再拼进正文** |

---

## 3. SSE 事件流映射（QAGraph 运行期）

```mermaid
sequenceDiagram
    participant F as "前端 useSSE"
    participant API as "API chat_service"
    participant G as "QAGraph"
    participant LLM as "DeepSeek 流式"

    F->>API: POST /chat/stream {message, kb_id}
    API->>API: 鉴权 + kb 归属校验，落库用户消息
    API->>G: ainvoke(QaState, thread_id=conv:msg)
    G-->>API: stream_mode updates 节点事件
    API-->>F: data: {"v":1,"t":"step","k":"intent","s":"done","metrics":{...}}
    API-->>F: data: {"v":1,"t":"step","k":"retrieval","s":"done","metrics":{...}}
    API-->>F: data: {"v":1,"t":"step","k":"fusion","s":"done","metrics":{...}}
    API-->>F: data: {"v":1,"t":"step","k":"answer","s":"pending"}
    G->>LLM: generate_answer 流式
    loop 每个 token
        LLM-->>G: adispatch_custom_event('token', {...})
        API-->>F: data: {"v":1,"t":"text","c":"..."}
    end
    API-->>F: data: {"v":1,"t":"cite","citations":[...]}
    G->>G: persist_message 落库
    API-->>F: data: {"v":1,"t":"done","conversation_id":"...","message_id":"..."}
    Note over API,F: 空闲期由独立 task 发送 {"v":1,"t":"heartbeat"}，防网关超时
```

### 双通道说明

| 通道 | 用途 | 实现 |
| --- | --- | --- |
| 节点级 `t:step` | 管线进度 + metrics | `graph.stream(stream_mode=['updates','values'])` |
| token 级 `t:text` | 回答流式 | `astream_events(version='v2')` + 节点内 `adispatch_custom_event('token')` → 消费端 `on_custom_event` |
| `t:heartbeat` | 防网关掐断 | 独立 asyncio task 定时写队列，**不放图内** |

> 注：不要在同一个循环里混用 `astream` 与 `astream_events`；节点事件与 token 流分两个通道。
