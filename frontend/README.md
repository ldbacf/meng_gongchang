# MedRAG Frontend — 医疗 RAG 智能问答前端

> 基于 Vue 3 + TypeScript 的医疗文献 RAG 对话界面。

## 📋 功能概述

- **智能对话** — 类 ChatGPT 问答，支持流式 SSE 实时输出、中断响应
- **文献引用** — 回答中 `[N]` 标记渲染为可点击引用卡片，点击查看文献详情
- **PDF 预览** — 内嵌 PDF 查看器，可直接定位引用内容
- **用户认证** — JWT 登录 + 自动 Token 刷新（并发 401 请求排队重试）
- **用户管理** — 管理员后台，支持添加/禁用/删除用户
- **响应式布局** — 可折叠侧栏，适配桌面端和移动端

## 🧰 技术栈

| 组件        | 技术                                              |
| ----------- | ------------------------------------------------- |
| 框架        | Vue 3 (Composition API + `<script setup>`)        |
| 语言/构建   | TypeScript + Vite 5                               |
| 状态/路由   | Pinia + Vue Router 4                              |
| 样式        | Tailwind CSS 3（毛玻璃顶栏 + 过渡动画）           |
| HTTP        | Axios（拦截器 / Token 刷新队列）                  |
| Markdown    | markdown-it + highlight.js + TeX                  |
| PDF 预览    | pdfjs-dist + vue-pdf-embed                        |

## 🚀 快速开始

前置条件：Node.js ≥ 18、npm ≥ 9、后端 API 已启动（见 [backend/README.md](../backend/README.md)）。

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 自动代理到 http://localhost:8000
npm run build      # 生产构建，产物在 dist/
npm run preview    # 预览构建结果
```

API 代理在 `vite.config.ts` 中配置，后端地址不同时修改 `server.proxy['/api'].target` 即可。

## 🔌 API 对接

统一使用 `@/api` 的 Axios 实例（自动附加 `Authorization` 头）：

```typescript
import api from '@/api'
await api.get('/v1/documents', { params: { page: 1 } })
await api.post('/v1/chat', { query: '高血压用药', top_k: 10 })
```

流式回答使用 `useSSE` composable：

```typescript
import { useSSE } from '@/composables/useSSE'
const { connect, disconnect } = useSSE({
  url: '/api/v1/chat/stream',
  onMessage: (data) => console.log(data.token),
  onDone: () => {},
  onError: (err) => {},
})
connect({ query: '高血压用药', top_k: 10 })
```

## 🧩 目录结构

```
frontend/
├── public/pdf/                  # 示例 PDF
└── src/
    ├── api/                     # Axios 实例 + 各模块 API
    ├── components/
    │   ├── chat/                # ChatView / MessageBubble / CitationCard / PdfViewer / RightPanel
    │   ├── common/              # AppLogo / LoadingSpinner / ToastContainer
    │   ├── layout/              # AppLayout / Sidebar
    │   └── admin/               # UserManagement
    ├── composables/             # useAuth / useSSE / useMarkdown
    ├── stores/                  # Pinia (auth, toast)
    ├── types/                   # TypeScript 类型
    ├── views/                   # 页面视图
    ├── App.vue / main.ts
```

## 📝 开发说明

- **新增页面**：在 `src/views/` 创建 `.vue` → 配置路由 → 在 `Sidebar.vue` 添加导航项
- **新增 API**：在 `src/api/` 建模块 → 用统一 Axios 实例 → 在 `src/types/` 定义类型
- **部署**：`dist/` 输出到 Nginx 等静态服务器，需将 `/api` 代理到后端

## 🐛 常见问题

- **白屏 / 路由无法访问** — 确认后端已启动、API 地址正确
- **登录后跳回登录页** — Token 过期，确认 `/api/v1/auth/refresh` 可用
- **流式输出卡住** — 确认后端返回 `text/event-stream`，Nginx 需 `proxy_buffering off`
