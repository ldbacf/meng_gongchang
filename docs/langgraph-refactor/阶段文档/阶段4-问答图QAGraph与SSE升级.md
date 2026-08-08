# 阶段 4：问答图 QAGraph 与 SSE 协议升级

> 归属：`docs/langgraph-refactor/阶段文档/阶段4-问答图QAGraph与SSE升级.md`
> 总纲依据：`docs/langgraph-refactor/总需求文档.md`（重点 §6.1 约束 C6/C7/C8、§6.3 问答图、§7.7 SSE v1）

---

## 一、核心目标

阶段 4 把**在线 RAG 问答**从 `chat.py` 单路由 490 行硬编码串行管线迁移为 **LangGraph 问答图**，收敛三处重复编排，并升级 SSE 协议到 v1（信封 + error/heartbeat）。兑现"SSE 中断丢回答、失败静默降级、协议无版本、指标漂移"缺陷的修复。

1. **O-4.1 QAGraph 落地**：`build_context→intent→expand→dual_recall→rrf→rerank→cite→answer→persist` 节点 DAG + `error_handler`；`chat_stream/search_with_intent/search_and_answer` 三处重复编排收敛为单图。
2. **O-4.2 SSE v1 协议**：阶段 0 冻结的 v 信封落地；新增 `t:error`、`t:heartbeat` 帧；metrics 构建收敛为单一函数。
3. **O-4.3 checkpoint 断点续跑**：用户消息落库后图开始，answer 中断从 rerank 重跑；`done` 帧携带 `message_id` 供前端幂等；token 级流式内容不进 checkpoint。
4. **O-4.4 失败降级可观测**：rerank/intent/检索失败节点级降级，`metrics.degraded` 显式记录，不再静默；错误不再拼进正文落库。
5. **O-4.5 KB 鉴权**：`chat_service`/`document_service` 入口强制校验 kb_id 归属（阶段 0 依赖层已有，此处业务层落实）。
6. **O-4.6 会话与流解耦**：SSE 生成器不再持有长活 db session，消息持久化在 `persist_message` 节点用独立短会话完成。

---

## 二、开发范围（含边界）

### 2.1 包含（In Scope）

| 编号 | 工作项 | 说明 |
| --- | --- | --- |
| S-4.1 | QAGraph | `application/graphs/rag_graph.py` + `state.py(QaState)` + `nodes/{build_context,intent,expand,dual_recall,rrf,rerank,cite,answer,persist,error}.py` |
| S-4.2 | chat_service | 会话 CRUD + 驱动 QAGraph + 消息持久化；收敛三处重复编排 |
| S-4.3 | SSE 投影器 | `interface/sse.py`：图事件 → `{v,t:step|text|cite|done|error|heartbeat}` 帧；心跳独立 asyncio task |
| S-4.4 | 流式集成 | `stream_mode=['updates','values']` 产节点事件 + `astream_events(v2)` + `adispatch_custom_event('token')` 产 token（约束 C7）；async 图 + sync 阻塞节点（C8） |
| S-4.5 | checkpoint | `thread_id=conversation_id:message_id`；方案①每节点落 Postgres（answer 不写 token 进 state），写频瓶颈再升级方案②（拆两段 compile） |
| S-4.6 | metrics 单函数 | `rag_steps_metrics` 统一构建，intent/retrieval/fusion/answer 共用一个工厂 |
| S-4.7 | KB 鉴权业务层 | chat/document service 入口校验 kb_id 归属 |
| S-4.8 | 引用/降级 | `CitationBuilder` 接入；degraded 标记进 rag_steps |

### 2.2 不包含（Out of Scope）

| 项 | 说明 |
| --- | --- |
| 不做入库图 | 阶段 3 已完成 |
| 不做 metrics/trace 采集基建 | 阶段 5 |
| 不做前端大改 | 旧前端兼容；前端 error/heartbeat 分支为可选增强（不阻塞验收） |
| 不改检索算法 | RRF/Rerank/双路语义保留 |

### 2.3 边界与约束

- 本阶段必须遵守约束 **C6（无选择性 checkpoint，方案①②二选一）、C7（SSE 双通道）、C8（async 图 + sync 节点，禁整图 to_thread）**。
- SSE 断连语义：**图继续执行至 `persist_message`**（不丢 AI 消息），`done` 帧支持延迟补投递。
- 旧前端无需改代码即可消费新协议（v 信封向后兼容，`t:error`/`t:heartbeat` 为增量）。
- 图状态与 DB 双写一致：节点结束把结果投影写 DB，`persist_message` 落库 AI 消息 + citations + rag_steps。

---

## 三、前置依赖

| 依赖 | 验收条件 |
| --- | --- |
| 阶段 0 | langgraph 依赖、checkpoint 表、SSE v1 契约冻结、pytest 全绿 |
| 阶段 1 | AppContainer、事件总线、ES/Milvus/Embedding 单工厂、KB 作用域依赖 |
| 阶段 2 | `domain/rag/*` 纯函数（intent 策略/RRF/CitationBuilder/prompts）、KBKind |
| 阶段 3 | langgraph-checkpoint-postgres 生产装配验证、retry_on/interrupt 契约测试（阶段 0 预留） |

---

## 四、功能清单与数据契约

### 4.1 功能清单

| 编号 | 功能 | 产出 |
| --- | --- | --- |
| F-4.1 | 问答图 | `rag_graph.py` + 节点 + `state.py(QaState)` |
| F-4.2 | chat_service | 会话 CRUD + 图驱动 + 持久化 |
| F-4.3 | SSE v1 投影 | `sse.py`（step/text/cite/done/error/heartbeat + v 信封） |
| F-4.4 | 流式双通道 | `astream_events v2` + `adispatch_custom_event` + 心跳 task |
| F-4.5 | metrics 工厂 | `rag_steps_metrics` 单函数 |
| F-4.6 | KB 鉴权 | service 层 kb_id 校验 |

### 4.2 数据契约（本阶段落地/变更）

**4.2.1 QaState（图状态）**

```python
QaState = {
  message_id: str, conversation_id: str, user_id: str,
  query: str, kb: {kb_id, es_index, milvus_collection, kb_kind, policy_ref},
  history: list[{role, content}],                  # 回答 10 turns / 意图 2 turns
  rewritten_query: str, intent: {name, confidence, coverage, degraded},
  expanded_query: str | None,
  hits: list[SearchHit] | None, reranked: list[SearchHit] | None,
  citations: list[{idx, doc_id, title, snippet, md5}] | None,
  answer: str | None, rag_steps: dict,             # 每步 {status, elapsed_ms, metrics}
  stream_buffer: str, error: {step, kind, message, retryable} | None, done: bool,
}
```

**4.2.2 SSE v1 帧（落地阶段 0 契约）**

```jsonc
{"v":1,"t":"step","k":"intent|retrieval|fusion|answer","s":"pending|running|done|failed","elapsed_ms":0,"metrics":{...}}
{"v":1,"t":"text","c":"…"}
{"v":1,"t":"cite","citations":[{idx,doc_id,title,snippet,md5}]}
{"v":1,"t":"done","conversation_id":"…","message_id":"…"}
{"v":1,"t":"error","code":"…","message":"…","retryable":false}
{"v":1,"t":"heartbeat"}
```
- `t:step` 的 `s` 增加 `running/failed` 态（前端可选消费）。
- metrics 字段由 `rag_steps_metrics` 统一产出：`intent{domain,coverage,rewritten_query,keywords,suggestion,degraded}`、`retrieval{milvus_hits,es_hits,after_dedup,routing,degraded}`、`fusion{input_count,output_count,model,top_scores,degraded}`、`answer{model,context_chunks,total_tokens,total_elapsed_ms,degraded}`。

**4.2.3 断连语义**

```
SSE 断开 / 前端 abort：
- 图继续执行至 persist_message（不丢 AI 消息）；done 帧经延迟补投递（前端可用 message_id 幂等）
- 不因客户端断开而中断图（除非超时保护）
```

**4.2.4 降级记录**

- 降级点：intent 失败（原 query 直通）、rerank 失败（原序返回）、检索异常（空 hits 明确提示）、LLM 流中断（重试一次后 error）。
- 每次降级在 `rag_steps[*].metrics.degraded = true` 记录原因，杜绝静默。

### 4.3 本阶段变更点

- `POST /api/v1/chat/stream` 内部由 event_generator 改为驱动 QAGraph；对外 wire 协议向前兼容。
- `search_with_intent` / `search_and_answer` 废弃（收敛到图节点）。
- `chat.py` 不再 import `search._get_es` 等私有全局。
- AI 消息不再把 `[错误:...]` 拼进正文；错误走 `t:error` 帧 + `persist_message` 落 failed 标记。

---

## 五、验收用例与自动化测试

### 5.1 验收用例（手动/端到端）

| 编号 | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A-4.1 | 旧前端兼容 | 不升级前端代码调 `chat/stream` | 流正常；step/text/cite/done 事件可解析 |
| A-4.2 | 完整问答 | 提问 → SSE 全流程 | intent/retrieval/fusion/answer 四步 done；citations≤5；done 带 message_id |
| A-4.3 | 中断续跑 | 回答生成中断开重连 | 从 rerank 续跑（重放 answer 段），不整条重来，AI 消息最终落库 |
| A-4.4 | 失败有 error 帧 | 强制 rerank 失败 | `t:error` 帧返回（code/retryable）；AI 消息落库标记 failed；正文不含 `[错误]` |
| A-4.5 | 降级可观测 | 意图识别降级 | rag_steps.intent.metrics.degraded=true，前端展示重写前 query |
| A-4.6 | KB 越权 | 无 KB 权限用户带 kb_id 提问 | 403（业务层 service 校验） |
| A-4.7 | 心跳 | 长回答流 | 空闲期收到 `t:heartbeat`，网关不掐断 |
| A-4.8 | 多轮指代 | "高血压怎么治"→"那它呢"（通用 KB） | 第二问经 intent 指代消解，检索语义正确 |

### 5.2 自动化测试清单

| 编号 | 测试 | 类型 | 断言要点 |
| --- | --- | --- | --- |
| T-4.1 | `test_rag_graph_happy_path` | 集成(全 fake + testcontainers) | 节点序列推进；persist 落库 citations+rag_steps；done 带 message_id |
| T-4.2 | `test_rag_graph_abort_resume` | 集成(InMemory saver) | 中断后同 thread_id 续跑仅重跑 answer 段 |
| T-4.3 | `test_sse_envelope` | 单元 | 每帧带 `v:1`；step/text/cite/done/error/heartbeat 结构符合契约 |
| T-4.4 | `test_sse_error_frame` | 单元 | rerank 抛错→error_handler 产出 `t:error`；AI 消息落库 failed；正文不含错误串 |
| T-4.5 | `test_metrics_single_source` | 单元 | intent/retrieval/fusion/answer metrics 由单一工厂产出，字段一致 |
| T-4.6 | `test_degraded_flags` | 单元 | 意图/重排失败时对应 metrics.degraded=true |
| T-4.7 | `test_kb_authz_service` | 集成 | 越权 kb_id 在 service 层被拒 |
| T-4.8 | `test_token_stream_not_in_checkpoint` | 集成 | checkpoint 中不包含 token 级流式内容（只含节点边界） |
| T-4.9 | `test_legacy_search_entry_removed` | 静态 | `search_with_intent/search_and_answer` 无调用方 |
| T-4.10 | `test_no_long_session_generator` | 静态 | SSE 生成器不使用 route 注入的长活 db session（短会话独立写） |

### 5.3 质量门槛

- 旧前端无改动跑通（A-4.1）。
- 中断续跑通过（A-4.3），AI 消息不丢。
- 失败有 error 帧且不再污染正文（A-4.4）。
- `t:heartbeat` 生效，长流不被网关掐断（A-4.7）。
- `grep -rn "search_with_intent\|search_and_answer" src/` 无命中。
