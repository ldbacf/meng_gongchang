# MedRAG 双前端架构 —— 管理端独立开发规格

> **用途**：交给 Codex 执行的技术规格书。可整份作为任务输入。
> **基准时间**：2026-10-25
> **架构决策**：**用户端与管理端彻底拆分为两个独立前端**（本节取代此前"合并进主前端"的方案）
> **状态**：✅ **已实施完成**（M1~M4 全部落地并验证通过，见文末「实施记录」）

---

## 实施记录（2026-10-25 完成）

| 里程碑 | 状态 | 产出 |
|---|---|---|
| M1 管理端骨架 | ✅ | axios 层 / auth store / toast / 登录页 / 路由守卫 / vite 代理 |
| M2 后端数据层 | ✅ | `operation_logs`、`retrieval_logs` 两表 + `users` 三列 + 检索埋点 + 12 处审计埋点 |
| M3 后端接口 | ✅ | 7 个统计接口，全部 `200`；非 admin 全部 `403` |
| M4 管理端六页 | ✅ | 6 页全接真实 API，`vue-tsc` + `vite build` 通过 |
| M5 用户端剥离 | ⏸ **按用户要求暂不执行** | 5173 保持原样，未删任何代码 |

**与规格的差异（已确认）**：

1. **封禁支持定时解封** —— 新增 `users.banned_until`，登录时惰性校验，过期自动恢复（无定时任务）。
2. **用户管理新增「新建用户」** —— Figma 未设计，但后端 `POST /admin/users` 已存在，接入。
3. **导出改为纯前端 CSV** —— 4 个页面的导出按钮均可用，零后端改动。
4. **登录日志标签从「管理员登录」改为「登录」** —— 该日志对全体用户生效，原名会误导。
5. **`messages.role` 是 `'user'` / `'ai'`**，不是 `'assistant'`（规格 §9 陷阱 1 已验证）。
6. **`active-users` 默认窗口从 7 天改为前端默认 30 天** —— 7 天窗口在历史数据上为空，看起来像故障。

**新增文件**：

- 后端：`src/log_service.py`、`src/routers/admin_stats.py`、`scripts/reset_password.py`
- 前端：`api/index.ts`、`api/auth.ts`、`api/admin.ts`、`stores/auth.ts`、`stores/toast.ts`、
  `views/LoginView.vue`、`views/KnowledgeListView.vue`、`views/KnowledgeDetailView.vue`、
  `components/common/{BaseModal,ToastContainer}.vue`、`composables/useDocumentWS.ts`、
  `types/{index,admin}.ts`、`utils/format.ts`

---

## 0. 目标形态

```
┌─────────────────────┐      ┌─────────────────────┐
│ 用户端  :5173        │      │ 管理端  :5174        │
│ meng_gongchang/     │      │ meng_gongchang_admin/│
│   frontend          │      │   frontend           │
│                     │      │                      │
│ · 登录/注册          │      │ · 登录（仅 admin）    │
│ · 对话（SSE 流式）   │      │ · 用户管理            │
│ · 引用卡片/PDF 预览  │      │ · 活跃用户            │
│ · 知识库选择         │      │ · 知识库统计          │
│ · 历史会话           │      │ · 操作日志            │
│                     │      │ · 知识库管理          │
│                     │      │ · 文档管理（WS）      │
└──────────┬──────────┘      └──────────┬──────────┘
           │                            │
           └────────────┬───────────────┘
                        ▼
              ┌───────────────────┐
              │ 后端  :8000        │
              │ FastAPI + 8 容器   │
              └───────────────────┘
```

**核心原则**：一个后端，两套前端，共用同一套 JWT。
两个前端是不同 origin（端口不同），**localStorage 天然隔离** —— 管理端登录状态不影响用户端，反之亦然。这是拆分的额外收益。

---

## 1. 当前状态与差距

### 1.1 用户端（`meng_gongchang/frontend`，5173）

| 项 | 状态 |
|---|---|
| 登录/注册/鉴权 | ✅ 完整 |
| axios + JWT 注入 + 401 自动刷新 | ✅ 完整（`api/index.ts` 93 行） |
| 对话 / SSE 流式 / 引用卡片 / PDF 预览 | ✅ 完整 |
| **包含 3 个 admin 路由** | ⚠️ **要剥离** |

现有 admin 路由（需删除）：`/admin/users`、`/admin/knowledge`、`/admin/knowledge/:kbId`

### 1.2 管理端（`meng_gongchang_admin/frontend`，5174）

| 项 | 状态 |
|---|---|
| 4 个页面 UI（用户/活跃/统计/日志） | ✅ 已有（`src/views/*.vue`，736 行） |
| 布局组件（`AdminLayout`/`AdminSidebar`/`MetricCard`/`BanModal`） | ✅ 已有 |
| Tailwind 设计 token | ✅ 已有（见 §5.6） |
| **axios 请求层** | ❌ **完全没有** |
| **登录页 / auth store** | ❌ 没有 |
| **路由守卫** | ❌ 没有 |
| **`/api` 代理** | ❌ 没配 |
| **Toast 提示** | ❌ 没有 |
| **知识库管理页** | ❌ 没有（Figma 漏设计） |
| **文档管理页 + WebSocket** | ❌ 没有（Figma 漏设计） |
| 数据 | ❌ 全部 mock（数组已清空） |

### 1.3 后端（`meng_gongchang/backend`，8000）

| 项 | 状态 |
|---|---|
| 12 个 admin 接口（用户 CRUD / 知识库 CRUD / 文档上传重试删除） | ✅ 完整可用 |
| `require_admin` 依赖 | ✅ 完整 |
| 文档状态 WebSocket 广播 | ✅ 完整 |
| **统计类接口** | ❌ 0 个 |
| **操作审计 / 检索埋点** | ❌ 0 个 |
| **非 admin 的知识库列表接口** | ❌ **没有（见 §2.1，阻塞项）** |

---

## 2. 两个必须先修的阻塞问题

### 2.1 【P0】用户端选知识库调的是 admin 接口

**证据**：`frontend/src/components/chat/ChatView.vue:132`

```ts
onMounted(async () => {
  await chatStore.fetchConversations()
  await adminStore.fetchKnowledgeBases()        // ← 打的是 /api/v1/admin/knowledge-bases
  if (!adminStore.activeKbId) { /* 选默认库 */ }
  const convId = route.params.id as string | undefined
  if (convId) chatStore.selectConversation(convId)
})
```

`src/api/knowledge.ts` → `fetchKnowledgeBasesApi()` → `GET /v1/admin/knowledge-bases` → 后端 `Depends(require_admin)`。

而 `stores/admin.ts:24` 的 `fetchKnowledgeBases()` **没有 try/catch**：

```ts
async function fetchKnowledgeBases() {
  kbLoading.value = true
  knowledgeBases.value = await fetchKnowledgeBasesApi()   // 403 直接抛出去
  kbLoading.value = false
}
```

**后果链**（普通 user 账号登录后）：

```
① fetchKnowledgeBases() 抛 403
② onMounted 中断，后续代码不再执行
③ 默认知识库没选上
④ chatStore.selectConversation(convId) 也没执行
   → 直接打开 /chat/:id 历史对话会空白
```

**修复**：后端新增**非 admin** 的 `GET /api/v1/knowledge-bases`（见 §4.3 U1），用户端改调它，并给 `fetchKnowledgeBases` 加 `try/catch`。

> 拆分后这个问题会更严重：5173 一旦删掉 admin 相关代码，用户端连"错误地调 admin 接口"都做不到了，必须走新接口。

### 2.2 【P0】CORS 没放行 5174

`backend/src/config.py:90`

```python
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
```

5174 **不在白名单**。虽然开发期用 vite proxy 可以绕过 CORS，但一旦改直连（或上生产）就会全站 401/CORS 报错。

**修复**：默认值追加 `http://localhost:5174`，同时 `.env` 里显式写一份。

---

## 3. 数据模型变更

### 3.1 决策摘要

| 对象 | 动作 | 理由 | 可省？ |
|---|---|---|---|
| `operation_logs` | 新建 | 操作日志页零数据源 | ❌ |
| `retrieval_logs` | 新建 | 知识库统计唯一可行数据源 | ❌ |
| `users.email` | 加列 | 用户表格要显示邮箱 | ❌ |
| `users.last_active_at` | 加列 | 活跃用户排序性能 | ⚠️ 可实时聚合 |
| 日汇总表 | **不建** | 当前万级数据量，实时聚合足够 | ✅ 不建 |

### 3.2 `operation_logs`

```sql
CREATE TABLE operation_logs (
    id             UUID PRIMARY KEY,
    operator_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    operator_name  VARCHAR(128) NOT NULL,
    operator_role  VARCHAR(16)  NOT NULL,
    action         VARCHAR(64)  NOT NULL,
    target_type    VARCHAR(32),
    target_id      VARCHAR(64),
    target_label   VARCHAR(512),
    detail         TEXT,
    ip             VARCHAR(45),
    severity       VARCHAR(16)  NOT NULL DEFAULT 'info',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_oplogs_created  ON operation_logs (created_at DESC);
CREATE INDEX ix_oplogs_operator ON operation_logs (operator_id);
CREATE INDEX ix_oplogs_action   ON operation_logs (action);
CREATE INDEX ix_oplogs_severity ON operation_logs (severity);
```

要点：
- `operator_name` / `operator_role` **冗余快照** —— 用户被删后 `operator_id` 变 NULL，但日志仍可读。
- `target_label` 存人类可读串（"用户 yicheng"），前端直接显示，不用 join。

**action 枚举**（与前端 `LogType` 一一对应）

| action | 前端显示 | 默认 severity |
|---|---|---|
| `auth.login` | 登录 | `info` |
| `auth.login_failed` | 登录失败 | `warn` |
| `user.create` | 新建用户 | `info` |
| `user.ban` | 用户封禁 | `danger` |
| `user.unban` | 用户解封 | `success` |
| `user.role_change` | 权限变更 | `warn` |
| `user.delete` | 删除用户 | `danger` |
| `kb.create` | 知识库创建 | `info` |
| `kb.delete` | 知识库删除 | `danger` |
| `kb.import` | 知识库导入 | `info` |
| `doc.upload` | 文档上传 | `info` |
| `doc.delete` | 文档删除 | `warn` |
| `doc.retry` | 文档重试 | `info` |
| `data.export` | 数据导出 | `info` |
| `system.config` | 系统配置 | `warn` |

### 3.3 `retrieval_logs`

```sql
CREATE TABLE retrieval_logs (
    id               BIGSERIAL PRIMARY KEY,
    user_id          UUID REFERENCES users(id) ON DELETE SET NULL,
    kb_id            UUID REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    conversation_id  UUID,
    message_id       UUID,
    query            TEXT,
    es_index         VARCHAR(80),
    es_hits          INT NOT NULL DEFAULT 0,
    milvus_hits      INT NOT NULL DEFAULT 0,
    fused_count      INT NOT NULL DEFAULT 0,
    cited_count      INT NOT NULL DEFAULT 0,
    top_score        REAL,
    latency_ms       INT,
    is_hit           BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_retlog_created ON retrieval_logs (created_at DESC);
CREATE INDEX ix_retlog_kb      ON retrieval_logs (kb_id, created_at DESC);
CREATE INDEX ix_retlog_user    ON retrieval_logs (user_id, created_at DESC);
```

`is_hit` 判定：`cited_count > 0`。

**埋点位置**：`backend/src/routers/chat.py` 第 218 行 `from src.search import rerank, search` 之后的检索段落，检索完成后写一条（异步、异常吞掉、不影响主流程）。

### 3.4 为什么 `retrieval_logs` 不可省（实测证据）

曾尝试"零新表"方案：从 `messages.citations` 反推知识库调用。**实测失败**：

```
被引 doc_id | 在 document_tasks 里存在
    7501    | false
    7557    | false
    8913    | false      ← 57 条全部 false
```

`citations` 的 `doc_id`（如 `8913`）指向 **ES 里的预置文献**（由 `scripts/import_es.py` 直接灌入），从未在 PostgreSQL 的 `document_tasks` 建行。因此**无法回溯到知识库**。

→ 只有 `retrieval_logs` 在检索发生时记录 `kb_id`，统计才可算。

### 3.5 `users` 扩列

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email
    ON users (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_users_last_active
    ON users (last_active_at DESC NULLS LAST);
```

⚠️ **必须走 `main.py` lifespan 的手写 `ALTER TABLE`**，不能只靠 `create_all`。

原因：`src/main.py:30` 的 `Base.metadata.create_all` **只创建不存在的表，不修改已存在的表**。`users` 已有 3 行数据，给 `User` 模型加字段不会生效。必须仿照现有 `main.py:34-43` 的写法追加。

### 3.6 SQLAlchemy 模型（写入 `backend/src/models.py`）

```python
from sqlalchemy import BigInteger   # 新增 import

class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    operator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    operator_role: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    es_index: Mapped[str | None] = mapped_column(String(80), nullable=True)
    es_hits: Mapped[int] = mapped_column(default=0, nullable=False)
    milvus_hits: Mapped[int] = mapped_column(default=0, nullable=False)
    fused_count: Mapped[int] = mapped_column(default=0, nullable=False)
    cited_count: Mapped[int] = mapped_column(default=0, nullable=False)
    top_score: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    is_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
```

---

## 4. 后端接口变更

### 4.1 总览

| # | 方法 | 路径 | 鉴权 | 类型 | 用途 |
|---|---|---|---|---|---|
| A1 | GET | `/admin/users` | admin | 🔧 改造 | 用户列表（分页+搜索） |
| A2 | GET | `/admin/users/metrics` | admin | 🆕 | 用户指标卡 |
| A3 | GET | `/admin/active-users` | admin | 🆕 | 活跃用户排行 |
| A4 | GET | `/admin/active-users/metrics` | admin | 🆕 | 活跃指标卡 |
| A5 | GET | `/admin/knowledge-stats` | admin | 🆕 | 知识库统计（含趋势+排行） |
| A6 | GET | `/admin/operation-logs` | admin | 🆕 | 操作日志列表 |
| A7 | GET | `/admin/operation-logs/metrics` | admin | 🆕 | 日志指标卡 |
| **U1** | GET | **`/knowledge-bases`** | **登录即可** | 🆕 | **用户端选知识库用**（§2.1 修复） |

全部前缀 `/api/v1`。

### 4.2 A1 · 用户列表（破坏性改造）

```
GET /api/v1/admin/users?page=1&page_size=20&search=&status=all&role=all
```

参数：`page`(默认1)｜`page_size`(默认20，上限100)｜`search`(匹配 username/email)｜`status`=`all|active|banned`｜`role`=`all|admin|user`

响应：
```json
{
  "items": [{
    "id": "uuid",
    "username": "yicheng",
    "email": "y@example.com",
    "role": "user",
    "enabled": true,
    "status": "正常",
    "chats": 4,
    "kbCalls": 12,
    "lastLogin": "2026-10-20T10:00:00+08:00",
    "registeredAt": "2026-08-30T19:20:00+08:00"
  }],
  "total": 3, "page": 1, "page_size": 20
}
```

- `chats` = 该用户 `conversations` 数
- `kbCalls` = 该用户 `retrieval_logs` 中 `is_hit=true` 的条数
- `status` 由 `enabled` 映射：`true→"正常"`、`false→"已封禁"`

⚠️ 由"裸数组"改成"分页对象"，**必须同步改** `frontend/src/api/user.ts`。

### 4.3 A2 / A4 / A7 · 指标卡

```
GET /api/v1/admin/users/metrics
→ { "total": 3, "normal": 3, "banned": 0, "todayNew": 0 }

GET /api/v1/admin/active-users/metrics
→ { "activeUsers": 3, "todayActive": 1, "kbCalls": 57, "avgChats": 11.0 }

GET /api/v1/admin/operation-logs/metrics
→ { "total": 0, "today": 0, "risky": 0, "adminOnline": 1 }
```
- `risky` = `severity IN ('warn','danger')`
- `adminOnline` = 最近 15 分钟内产生过操作日志的 admin 去重数

### 4.4 A3 · 活跃用户排行

```
GET /api/v1/admin/active-users?days=7&limit=20
```
```json
{
  "items": [{
    "userId": "uuid", "name": "admin", "email": null,
    "chats": 26, "kbCalls": 0, "sessions": 14,
    "lastActive": "2026-10-24T21:00:00+08:00", "score": 26
  }]
}
```

聚合口径（**必须写进代码注释**）：

| 字段 | 口径 |
|---|---|
| `sessions` | `count(DISTINCT conversations.id)` |
| `chats` | `count(messages.id) WHERE role='ai'` |
| `lastActive` | `max(messages.created_at)` |
| `kbCalls` | `count(retrieval_logs.id) WHERE is_hit` |
| `score` | `chats + kbCalls * 2` |

⚠️ `messages.role` 的值是 **`'user'` / `'ai'`**，不是 `'assistant'`。

### 4.5 A5 · 知识库统计

```
GET /api/v1/admin/knowledge-stats?days=7
```
```json
{
  "metrics": { "totalEntries": 1267, "totalCalls": 0, "todayCalls": 0, "hitRate": 0.0 },
  "trend": [ { "day": "2026-10-19", "value": 0 } ],
  "ranks": [ { "title": "中国全科医学", "tag": "chunks", "calls": 0 } ]
}
```

| 字段 | 口径 |
|---|---|
| `totalEntries` | `count(document_tasks)` |
| `totalCalls` | `count(retrieval_logs)`（受 `days` 过滤） |
| `todayCalls` | 今日 `count(retrieval_logs)` |
| `hitRate` | `is_hit=true / 总数`，**返回 0~1 小数**，前端转百分比 |
| `trend` | 按 `date_trunc('day', created_at)` 分组，**缺失日期补 0**，长度必须等于 `days` |
| `ranks` | 按 `kb_id` 分组计数降序取前 10，`tag` 用 `es_index` |

### 4.6 A6 · 操作日志列表

```
GET /api/v1/admin/operation-logs?page=1&page_size=20&type=&severity=&q=&from=&to=
```
```json
{
  "items": [{
    "id": "uuid",
    "time": "2026-10-25T14:00:00+08:00",
    "operatorName": "admin", "operatorRole": "admin",
    "type": "用户封禁", "action": "user.ban",
    "target": "用户 yicheng", "detail": "理由：违规",
    "ip": "127.0.0.1", "severity": "danger"
  }],
  "total": 0, "page": 1, "page_size": 20
}
```
`type` 由 `action` 查表翻译中文（映射见 §3.2）。

### 4.7 U1 · 公开知识库列表【新增，修复 §2.1】

```
GET /api/v1/knowledge-bases
Authorization: Bearer <任意已登录用户>
```
```json
[
  { "id": "uuid", "name": "中国全科医学", "description": "全科医学文献库",
    "slug": "zhong_guo_quan_ke", "document_count": 1250, "has_ready_docs": true }
]
```

**只返回对用户有意义的字段** —— 不含 `es_index` / `milvus_collection`（内部实现细节）。
建议新建 `backend/src/routers/knowledge.py`，`Depends(get_current_user)`（非 admin）。

### 4.8 CORS 修改

`backend/src/config.py:90`

```python
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:5174",
)
```

同时在 `backend/.env` 与 `.env.example` 补：

```
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
```

---

## 5. 管理端（5174）改造

### 5.1 要补的骨架（按依赖顺序）

| # | 文件 | 来源 | 行数参考 | 说明 |
|---|---|---|---|---|
| 1 | `src/api/index.ts` | 复制自 `meng_gongchang/frontend/src/api/index.ts` | 93 | axios 实例 + JWT 注入 + 401 自动刷新 + 队列重放。**原样搬，别改逻辑** |
| 2 | `src/api/auth.ts` | 复制自主前端同名文件 | ~20 | login / logout / me / refresh |
| 3 | `src/stores/auth.ts` | 复制自主前端同名文件 | 67 | token/user 持久化 + `isAdmin` |
| 4 | `src/stores/toast.ts` | 复制自主前端同名文件 | 32 | 轻量提示 |
| 5 | `src/components/common/ToastContainer.vue` | 复制自主前端 | 47 | 挂到 `App.vue` |
| 6 | `src/views/LoginView.vue` | 复制自主前端 | 112 | **需按 Figma 风格重做样式** |
| 7 | `src/router/index.ts` | 改造现有 | 32→90 | 加 `/login` + `beforeEach` 守卫 |
| 8 | `vite.config.ts` | 改造 | 20→30 | 加 `/api` 代理 |
| 9 | `src/types/admin.ts` | 从 `data/mock.ts` 提取 | — | **只留 type，删掉所有数组** |
| 10 | `src/api/admin.ts` | 新写 | ~120 | 全部 admin 接口客户端 |

### 5.2 `vite.config.ts` 加代理

```ts
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: true },
    },
  },
})
```

`ws: true` 必需 —— 文档管理页要连文档状态 WebSocket。

### 5.3 路由与守卫

```ts
// src/router/index.ts
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' } },
    {
      path: '/',
      component: () => import('@/components/layout/AdminLayout.vue'),
      redirect: '/users',
      children: [
        { path: 'users',           name: 'users',    component: () => import('@/views/UsersView.vue'),           meta: { title: '用户管理' } },
        { path: 'active-users',    name: 'active',   component: () => import('@/views/ActiveUsersView.vue'),     meta: { title: '活跃用户' } },
        { path: 'knowledge-stats', name: 'kbstats',  component: () => import('@/views/KnowledgeStatsView.vue'),  meta: { title: '知识库统计' } },
        { path: 'logs',            name: 'logs',     component: () => import('@/views/OperationLogsView.vue'),   meta: { title: '操作日志' } },
        { path: 'knowledge',       name: 'kb',       component: () => import('@/views/KnowledgeListView.vue'),   meta: { title: '知识库管理' } },
        { path: 'knowledge/:kbId', name: 'kbdetail', component: () => import('@/views/KnowledgeDetailView.vue'), meta: { title: '文档管理' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/users' },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  const user = JSON.parse(localStorage.getItem('user') ?? 'null')

  if (!to.meta.public && !token) return { name: 'login' }
  if (to.name === 'login' && token) return { name: 'users' }
  // 管理端只放行 admin
  if (token && user?.role !== 'admin') {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    return { name: 'login' }
  }
})
```

**侧边栏 5 项**：用户管理 / 活跃用户 / 知识库统计 / 知识库管理 / 操作日志。
（文档管理是 `/knowledge/:kbId` 子页，不进侧边栏。）

### 5.4 需要新写的两个页面

Figma 设计**漏了这两个页面**，但没有它们管理端无法操作数据。

#### `views/KnowledgeListView.vue` — 知识库管理

迁移自 `meng_gongchang/frontend/src/views/KnowledgeBaseView.vue`（226 行），**并用 Figma 设计 token 重做样式**。

| 区域 | 内容 |
|---|---|
| 工具栏 | 新建知识库按钮（弹窗：name / slug / description） |
| 卡片网格 | 每张卡：名称、描述、文档数、"只读/可上传"标记、slug |
| 卡片操作 | 「进入」→ `/knowledge/:kbId`；「删除」（二次确认） |

#### `views/KnowledgeDetailView.vue` — 文档管理

迁移自 `meng_gongchang/frontend/src/views/KnowledgeBaseDetailView.vue`（326 行）+ `composables/useDocumentWS.ts`（110 行）。**这是最重的一块**。

| 区域 | 内容 |
|---|---|
| 头部 | 返回、知识库名、只读/可上传标记 |
| 操作 | 上传 PDF（multipart）、删除、重试（从首个失败步骤） |
| 文档列表 | 每行展示 **6 步流水线**：`upload → mineru → chunking → embedding → es_write → milvus` |
| 实时更新 | WebSocket 推送 `doc_update` / `doc_deleted`，无需手动刷新 |

> 迁移时必须保留"从第一个失败步骤重试"的逻辑（后端 `POST /documents/{id}/retry` 返回 `retry_from`）。

### 5.5 四个现有页面接真实 API

| 页面 | 改动 |
|---|---|
| `UsersView.vue` | `users` 从 `mock` → `GET /admin/users`（分页/搜索/筛选走后端）；`userMetrics` → `GET /admin/users/metrics`；封禁后刷新列表 |
| `ActiveUsersView.vue` | `activeUsers` → `GET /admin/active-users`；`activeMetrics` → `/admin/active-users/metrics` |
| `KnowledgeStatsView.vue` | `kbMetrics`/`kbTrend`/`kbRanks` → 一次 `GET /admin/knowledge-stats` |
| `OperationLogsView.vue` | `operationLogs` → `GET /admin/operation-logs`；`logMetrics` → `/admin/operation-logs/metrics` |

**要求**：所有页面删除 `import ... from '@/data/mock'`，改为 `api/admin.ts`。空状态保留现有「暂无…」文案。

### 5.6 设计 token 补齐

现有 `tailwind.config.js` 缺 **warning** 色（操作日志的 `warn` 档位、指标卡的"异常/风险"要用）：

```js
colors: {
  // ...现有
  warning: { DEFAULT: '#F59E0B', soft: '#FFFBEB' },
},
```

现有 token 供参考：`primary #3B82F6/soft #EFF6FF`、`app-bg #FFFFFF`、`app-sidebar #F7F8FA`、`app-muted #F3F4F6`、`ink-primary #111827`、`ink-secondary #6B7280`、`ink-muted #9CA3AF`、`line #E5E7EB`、`danger #EF4444/soft #FEF2F2`、`success #10B981/soft #ECFDF5`；radius `sm 8px / md 12px / lg 16px`。

### 5.7 趋势图：不要装图表库

项目当前 0 个图表依赖。为一张 7 日趋势图引入 ECharts（~1MB）不划算。新建 `components/common/MiniTrend.vue`（约 80 行，纯 SVG polyline + 面积填充）。

---

## 6. 用户端（5173）改造 —— 剥离管理端

| # | 改动 | 文件 | 说明 |
|---|---|---|---|
| 1 | 删除 3 条 admin 路由 | `src/router/index.ts` | `/admin/users`、`/admin/knowledge`、`/admin/knowledge/:kbId` |
| 2 | 侧边栏移除「管理后台」区块 | `components/layout/Sidebar.vue:69-100` | 改为一个外链按钮「管理后台」，`window.open('http://localhost:5174')`，仅 admin 可见 |
| 3 | **知识库列表改走公开接口** | `components/chat/ChatView.vue:132` | `adminStore.fetchKnowledgeBases()` → 新 `kbStore.fetchKnowledgeBases()`（调 U1） |
| 4 | 给 fetch 加 try/catch | 新 store | 失败不阻塞 `onMounted` 后续逻辑（修 §2.1） |
| 5 | 删除 admin 组件与 store | `components/admin/*`、`views/UserManagementView.vue`、`views/KnowledgeBaseView.vue`、`views/KnowledgeBaseDetailView.vue`、`stores/admin.ts`、`api/user.ts`、`api/knowledge.ts` | **迁移验证通过后再删**，先留着备份 |
| 6 | 新增 `stores/kb.ts` | 新文件 | 用户端专用知识库 store（只读 + `activeKbId`） |

⚠️ 第 5 项顺序很重要：**先把 5174 的知识库/文档管理页跑通并验证，再删 5173 的**。否则中间状态两边都不能上传文档。

---

## 7. 任务拆解

### M1 · 管理端骨架（约 2h）

目标：**5174 能登录、能发请求、能守着权限**。

| ID | 任务 | 验收 |
|---|---|---|
| T1.1 | 搬 `api/index.ts` / `api/auth.ts` / `stores/auth.ts` / `stores/toast.ts` / `ToastContainer.vue` | 无 TS 报错 |
| T1.2 | 新写 `LoginView.vue`（Figma 风格） | 能输入账号密码 |
| T1.3 | 改 `router/index.ts` 加 `/login` + 守卫 | 未登录访问 `/users` 跳 `/login` |
| T1.4 | `vite.config.ts` 加 `/api` 代理（含 `ws:true`） | `curl localhost:5174/api/v1/health` 通 |
| T1.5 | 登录后校验 `role==='admin'`，非 admin 清 token 退回登录页 | 普通用户登录被拒 |

**验收**：用 admin 账号登录 → 进入 `/users`（空表格）→ 刷新页面不掉登录态。

### M2 · 后端数据层（约 2h）

| ID | 任务 | 验收 |
|---|---|---|
| T2.1 | `models.py` 加 `OperationLog` / `RetrievalLog`；`User` 加 `email`/`last_active_at` | 导入无错 |
| T2.2 | `main.py` lifespan 补 2 条 `ALTER TABLE` | 重启后 `\d users` 有 email 列 |
| T2.3 | 新建 `src/log_service.py`（`log_operation` + `get_client_ip`） | 能写能查 |
| T2.4 | `chat.py` 检索埋点 | 问答一次 → `retrieval_logs` +1，`kb_id` 非空 |
| T2.5 | 12 个 admin 写端点 + 登录插日志 | 封禁一个用户 → `operation_logs` +1 |
| T2.6 | `config.py` + `.env` 加 CORS 5174 | 预检请求通过 |

**验收**：`\dt` 出现两张新表；一次问答 + 一次封禁后两表都有数据。

### M3 · 后端接口（约 3h）

| ID | 任务 | 验收 |
|---|---|---|
| T3.1 | `schemas.py` 补 8 组响应模型 | 导入无错 |
| T3.2 | **U1 公开知识库列表**（新路由文件 `knowledge.py`） | 普通 user token 能拿到列表 |
| T3.3 | A1 改造 `/admin/users`（分页+搜索+email+chats+kbCalls） | 返回 `{items,total,page,page_size}` |
| T3.4 | A2 / A4 / A7 三个 metrics 接口 | 数字与 `psql` 手查一致 |
| T3.5 | A3 活跃用户 | admin 的 chats=26 与实测一致 |
| T3.6 | A5 知识库统计 | `trend` 长度 == `days`，日期连续 |
| T3.7 | A6 操作日志列表 | 分页/筛选生效，`type` 已译中文 |

**验收**：8 个接口全 `200`，非 admin 访问 A* 全 `403`、访问 U1 全 `200`。

### M4 · 管理端六页联通（约 4h）

| ID | 任务 | 验收 |
|---|---|---|
| T4.1 | `types/admin.ts` 从 mock 提类型，删所有数组 | `mock.ts` 可删 |
| T4.2 | 新写 `api/admin.ts`（8 个方法） | — |
| T4.3 | 4 个现有页面接真实 API | 无 `@/data/mock` 引用 |
| T4.4 | 迁移 `KnowledgeListView.vue` + Figma 样式 | 能新建/删除知识库 |
| T4.5 | 迁移 `KnowledgeDetailView.vue` + `useDocumentWS` | 上传 PDF 后流水线实时跳动 |
| T4.6 | 侧边栏 5 项 + `MiniTrend.vue` | 无新依赖 |
| T4.7 | `tailwind.config.js` 补 `warning` | warn 档位有颜色 |

**验收**：`npm run build` 通过；6 页全部真实数据；上传一篇 PDF 能看到 6 步推进。

### M5 · 用户端剥离（约 1.5h）

| ID | 任务 | 验收 |
|---|---|---|
| T5.1 | 新增 `GET /api/v1/knowledge-bases` 的客户端 + `stores/kb.ts` | — |
| T5.2 | `ChatView.vue` 改调新 store，加 try/catch | 普通 user 登录后能选知识库、能打开历史对话 |
| T5.3 | 删除 3 条 admin 路由 | 访问 `/admin/*` 落到 404 重定向 |
| T5.4 | 侧边栏「管理后台」改外链 5174 | 点击跳转 |
| T5.5 | 删除 admin 组件/store/api（**确认 5174 已跑通后**） | `grep -r "adminStore" src/` 无结果 |

**验收**：普通 user 账号登录 5173 全流程正常（选库 → 提问 → 看引用 → 看历史）；admin 账号能看到「管理后台」入口跳转 5174。

### M6 · 验收（约 1h）

| ID | 任务 |
|---|---|
| T6.1 | `scripts/verify_admin.py` 端到端断言（8 接口 + 权限边界） |
| T6.2 | 数据一致性：页面数字 == `psql` 查询 |
| T6.3 | 双端回归：5173 用户全流程 + 5174 管理员全流程 |

---

## 8. 验收清单（Definition of Done）

**后端**
- [ ] `\dt` 含 `operation_logs`、`retrieval_logs`
- [ ] `\d users` 含 `email`、`last_active_at`
- [ ] 8 个新接口全部 `200`
- [ ] 非 admin 访问 A1~A7 全部 `403`
- [ ] 普通 user 访问 U1 返回 `200` 且不含 `es_index`
- [ ] 问答一次 → `retrieval_logs` +1 且 `kb_id` 正确
- [ ] 封禁/解封 → `operation_logs` 各 +1，severity 分别 `danger`/`success`
- [ ] CORS 预检从 `http://localhost:5174` 发起通过

**管理端 5174**
- [ ] 未登录访问任意页 → 跳 `/login`
- [ ] 普通 user 账号登录 → 被拒绝且清空 token
- [ ] admin 登录 → 6 页全部可达
- [ ] 刷新页面登录态保持
- [ ] 用户管理：搜索/筛选/分页走后端，封禁后列表刷新
- [ ] 知识库管理：能新建、能删除
- [ ] 文档管理：上传 PDF → 6 步流水线实时推进 → 可重试/删除
- [ ] 知识库统计：4 个指标与 SQL 一致；趋势 7 个点无空缺
- [ ] 操作日志：能按类型/severity 筛选
- [ ] `grep -r "data/mock" src/` 无结果
- [ ] `npm run build` 通过

**用户端 5173**
- [ ] 普通 user 登录 → 能选知识库（**修复 §2.1**）
- [ ] 普通 user 打开 `/chat/:id` 历史对话正常（不再空白）
- [ ] `/admin/*` 已移除
- [ ] 侧边栏「管理后台」跳转 5174
- [ ] 对话/SSE/引用/PDF 预览全部正常

---

## 9. 已知陷阱（先读再动手）

1. **`messages.role` 是 `'user'` / `'ai'`，不是 `'assistant'`。** 统计 SQL 写 `role='ai'`，否则永远 0。
2. **`create_all` 不给已有表加字段。** 新表会自动建，但 `users.email` 必须手写 `ALTER TABLE`。
3. **预置文献不在 `document_tasks` 表。** 「中国全科医学」的 1250 篇直接灌进 ES，`citations.doc_id`（如 `8913`）在 Postgres 查不到。任何从 `citations` 反推知识库统计的写法都会得到 NULL。
4. **`中国全科医学` 与其他库共用 ES 索引。** 它的 `es_index` 是 `chunks`（28,759 篇共享），而 `document_count` 是 1250 —— 两者不相等是正常的。
5. **有 10 个残留测试库**（都叫「阶段3测试库」，各 1 篇）。统计页会显示，不是 bug。
6. **A1 是破坏性变更**（裸数组 → 分页对象），必须同步改 `frontend/src/api/user.ts`。
7. **不要装图表库。** 用 `MiniTrend.vue`（纯 SVG）。
8. **`operation_logs` 写入绝不能影响主流程。** `log_operation` 内部必须 `try/except` 吞掉异常并 `logger.warning`。
9. **两个前端的 localStorage 是隔离的**（不同端口 = 不同 origin）。管理员在 5174 登录，不影响 5173 的用户登录态。**不要试图共享 token**。
10. **`vite` 代理必须带 `ws: true`**，否则文档管理页的 WebSocket 连不上。
11. **迁移顺序**：先跑通 5174 的知识库/文档页，**再**删 5173 的。否则中途两边都无法上传文档。

---

## 10. 当前环境与验证方式

```bash
# 中间件（8 容器，已在跑）
cd backend && docker compose up -d

# 后端
cd backend && .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000

# 用户端
cd frontend && npm run dev            # :5173

# 管理端
cd ../meng_gongchang_admin/frontend && npm run dev   # :5174
```

| 服务 | 地址 |
|---|---|
| 用户端 | http://localhost:5173 |
| 管理端 | http://localhost:5174 |
| 后端 API 文档 | http://localhost:8000/docs |
| Kibana | http://localhost:5601 |
| Attu (Milvus) | http://localhost:8002 |
| MinIO 控制台 | http://localhost:9001 |

**现有数据基线**（验收对照）：

| 表 | 行数 |
|---|---|
| `users` | 3（admin / yicheng / ldbacf） |
| `conversations` | 17 |
| `messages` | 33（user 20 / ai 13） |
| `document_tasks` | 1262 |
| `knowledge_bases` | 13 |
| ES `chunks` | 28,759 篇 / 56.1 MB |
| Milvus | 1 collection：`chunks` |

账号密码为 bcrypt 哈希，需自行重置或先跑一个改密脚本。
