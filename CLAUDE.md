# CLAUDE.md — MedRAG 医学文献助手

## 项目概况

基于 Vue 3 + TypeScript 的医学文献 RAG（检索增强生成）智能问答 SPA。用户通过对话形式向 AI 提问，AI 基于真实医学期刊文献生成回答。当前为纯 Mock 模式（无需后端），数据通过 localStorage 持久化。

- **项目名**: `medical-rag-assistant`
- **开发命令**: `npm run dev` → `http://localhost:3000`
- **构建命令**: `npm run build`（类型检查 + Vite 构建）
- **界面语言**: 中文 (zh-CN)

## 技术栈

| 层级 | 选型 |
|---|---|
| 框架 | Vue 3.4（Composition API，`<script setup>`） |
| 语言 | TypeScript 5.4（strict 模式） |
| 构建 | Vite 5.4 |
| 路由 | vue-router 4.3（history 模式） |
| 状态管理 | Pinia 2.1 |
| 样式 | Tailwind CSS 3.4（class 暗色模式，自定义 blue 主色调） |
| HTTP | axios 1.7（baseURL `/api`，自动附带 auth header） |
| Markdown 渲染 | markdown-it 14 + highlight.js 11.9 |
| PDF 查看 | vue-pdf-embed（基于 pdfjs-dist 5.7） |
| 图标 | lucide-vue-next 0.378 |
| 工具库 | @vueuse/core 10.9 |

## 路由表

| 路径 | 名称 | 需要登录 | 需要管理员 | 视图文件 |
|---|---|---|---|---|
| `/login` | Login | ✗ | — | `src/views/LoginView.vue` |
| `/chat` | Chat | ✓ | — | `src/views/ChatView.vue` |
| `/chat/:id` | ChatConversation | ✓ | — | `src/views/ChatView.vue` |
| `/admin/knowledge` | KnowledgeBase | ✓ | ✓ | `src/views/KnowledgeBaseView.vue` |
| `/admin/users` | UserManagement | ✓ | ✓ | `src/views/UserManagementView.vue` |
| `/` | 重定向 → `/chat` | — | — | — |
| `/:pathMatch(.*)*` | 兜底 → `/chat` | — | — | — |

路由守卫在 `src/router/index.ts:50`，检查 localStorage 中的 `token` 和 `user.role`。

## 目录结构

```
src/
├── api/              # axios 请求函数，每个都有 mock 降级
│   ├── index.ts      # axios 实例 + 拦截器（auth header、401 跳转）
│   ├── auth.ts       # loginApi()
│   ├── chat.ts       # fetchConversationsApi()、fetchMessagesApi()、deleteConversationApi()
│   ├── knowledge.ts  # fetchDocumentsApi()、uploadDocumentApi()、deleteDocumentApi()
│   ├── document.ts   # fetchDocumentPdfApi() — doc-001/002/003 映射到 /pdf/*.pdf
│   └── user.ts       # fetchUsersApi()、toggleUserStatusApi()
├── components/
│   ├── admin/        # KnowledgeBase.vue、UserManagement.vue
│   ├── chat/         # ChatView.vue（核心聊天逻辑）、ChatInput.vue、MessageBubble.vue、
│   │                 # AiMessage.vue、UserMessage.vue、CitationCard.vue、
│   │                 # CitationSummary.vue、ConversationList.vue、RightPanel.vue、
│   │                 # RagPipelineSimple.vue（可展开的 RAG 步骤时间线）
│   ├── common/       # AppLogo.vue、LoadingSpinner.vue
│   └── layout/       # AppLayout.vue（侧边栏 + 顶栏 + slot）、Sidebar.vue、TopHeader.vue
├── composables/      # useAuth.ts、useMarkdown.ts（markdown-it + citation-tag 标签转换）、useSSE.ts
├── mock/             # index.ts — 所有 mock 数据（对话、消息、文档、用户）
│                     # USE_MOCK 开关（当前为 true）、simulateDelay() 辅助函数
├── router/           # index.ts
├── stores/           # auth.ts、chat.ts（按用户持久化到 localStorage）、admin.ts
├── types/            # auth.ts、chat.ts、knowledge.ts、user.ts、index.ts（统一导出）
├── views/            # LoginView.vue、ChatView.vue、KnowledgeBaseView.vue、UserManagementView.vue
├── App.vue           # 仅含 <RouterView />
├── main.ts           # createApp → Pinia → Router → 挂载 #app
└── style.css         # Tailwind 指令 + markdown-body 样式 + 滚动条 + citation-tag 样式
pdf/                  # 3 篇用于右侧面板 PDF 查看器的模拟文献 PDF
public/               # 静态资源（favicon 等）
```

## 核心架构模式

### Mock 系统
- `src/mock/index.ts` 导出 `USE_MOCK = true`——**每个 API 文件都检查此开关**，启用时返回 mock 数据并调用 `simulateDelay()`。
- 切换到真实后端的方法：将 `USE_MOCK` 设为 `false`，并取消 `vite.config.ts` 中 proxy 的注释。
- Mock 登录：任意密码可登录；用户名为 `admin` → 管理员角色，其他任意用户名 → 普通用户角色。

### 状态管理（Pinia）
- **auth store** (`useAuthStore`): `token`、`user`、`isAdmin`、`isAuthenticated`。登录信息持久化到 localStorage（键名 `token`、`user`）。401 响应或登出时清除。
- **chat store** (`useChatStore`): 对话和消息按用户存储到 localStorage（`medrag_{用户名}_conversations`、`medrag_{用户名}_messages`）。新用户首次登录自动播种 mock 数据（`medrag_{用户名}_seeded` 标志位）。流式状态：`isStreaming`、`streamContent`、`streamCitations`，用于逐字动画展示。
- **admin store** (`useAdminStore`): `documents` 数组用于知识库 CRUD，`users` 数组用于用户启用/禁用切换。

### 对话流程（Mock 管道）
1. 用户输入消息 → `ChatView.vue` 中的 `handleSend()`
2. 若无当前对话，先创建一个 → 路由替换到 `/chat/:id`
3. `chatStore.addUserMessage()` → 持久化到 localStorage
4. `chatStore.startStreaming()` → 设置 `isStreaming = true`
5. `runMockPipeline()` 通过关键词匹配检测场景（4 个场景：心血管、copd、基层评价、默认）
6. RAG 步骤按顺序动画展示（延时 500ms/1000ms/1500ms/2000ms）：意图识别 → 混合检索 → 融合重排 → 门神评估
7. 文本逐字流式输出（约 40ms 间隔） → 附加引用 → `chatStore.finishStreaming()`

### 登录后聊天页组件树
```
AppLayout.vue
├── Sidebar.vue
│   ├── AppLogo.vue
│   └── ConversationList.vue
└── ChatView.vue（主 slot 内容）
    ├── MessageBubble.vue（×N）
    │   ├── UserMessage.vue
    │   └── AiMessage.vue
    │       ├── RagPipelineSimple.vue（可展开的 RAG 时间线）
    │       │   └── 4 个步骤节点：意图识别、混合检索、融合重排、门神评估
    │       ├── [渲染后的 markdown，内含 citation-tag span]
    │       └── CitationCard.vue（×N，点击弹出 mock PDF 弹窗）
    ├── CitationSummary.vue（底部椭圆按钮："📚 参考文献 (N)"）
    ├── ChatInput.vue（textarea + 发送按钮）
    └── RightPanel.vue（从右侧滑入，420px 宽，文献列表或 vue-pdf-embed PDF 查看器）
```

### 认证流程
- 登录触发 `loginApi()` → 无论成功或 catch，都生成 fake JWT（`btoa(用户名:时间戳)`）→ 将 `token` + `user` 存入 localStorage
- 路由守卫在每次导航时检查 `localStorage.token`
- axios 拦截器自动附加 `Authorization: Bearer <token>` 请求头
- 收到 401 响应 → 清除认证信息，跳转 `/login`

### 用户数据隔离
- 每个用户的对话和消息存储在以 `medrag_{用户名}_*` 为键名的 localStorage 中
- 首次登录自动创建 3 个含预设消息的演示对话
- 不同用户只能看到自己的聊天记录

## 关键依赖

| 包 | 用途 |
|---|---|
| `lucide-vue-next` | 全部图标（Stethoscope、Send、Trash2、Sparkles 等） |
| `@vueuse/core` | `useMemoize`（markdown 渲染缓存） |
| `markdown-it` + `highlight.js` | AI 回复 markdown → 带代码高亮的 HTML |
| `vue-pdf-embed` | 右侧面板 PDF 渲染（基于 pdfjs-dist） |
| `pinia` | 状态管理 |
| `vue-router` | 客户端路由 |

## 项目当前状态

- **Mock 模式下功能完整**——无需后端即可运行
- 全部 UI 功能已实现：登录、流式聊天、RAG 管道可视化、引文面板 + PDF 查看器、对话管理、知识库 CRUD、用户管理
- 3 个演示用户：`admin`（管理员）、`doctor_zhang`（普通用户）、`researcher_li`（普通用户，默认禁用）
- 3 个预置对话，涵盖心血管风险评估、COPD 合并高血压、基层卫生服务评价
- 后端对接准备工作已完成（API 层结构就绪、proxy 配置已写好，只需翻转 `USE_MOCK` 开关）
- 暂无测试
