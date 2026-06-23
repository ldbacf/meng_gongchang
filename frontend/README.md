# MedRAG Frontend — 医疗 RAG 智能问答前端

> 基于 Vue 3 + TypeScript 的医疗文献 RAG 对话界面。

---

## 📋 功能概述

前端提供面向基层医疗场景的 RAG 问答交互界面：

- **智能对话** — 类 ChatGPT 交互式问答，支持流式 SSE 实时输出
- **文献引用** — 回答内容自动标注引用来源，点击查看文献详情
- **PDF 预览** — 内嵌 PDF 查看器，可直接在原文献中定位引用内容
- **用户认证** — JWT 登录 + 自动 Token 刷新
- **用户管理** — 管理员后台，管理用户账号与权限
- **响应式布局** — 可折叠侧栏，适配桌面端和移动端

---

## 🧰 技术栈

| 组件           | 技术                                |
| -------------- | ----------------------------------- |
| 框架           | Vue 3 (Composition API + `<script setup>`) |
| 语言           | TypeScript                          |
| 构建工具       | Vite 5                              |
| 状态管理       | Pinia                               |
| 路由           | Vue Router 4                        |
| 样式           | Tailwind CSS 3                      |
| HTTP 客户端    | Axios (拦截器/Token 刷新队列)       |
| Markdown 渲染  | markdown-it + highlight.js + TeX    |
| PDF 预览       | pdfjs-dist + vue-pdf-embed          |
| 图标           | lucide-vue-next                     |

---

## 📁 目录结构

```
frontend/
├── public/
│   └── pdf/                          # 示例 PDF 文件
├── src/
│   ├── api/                          # API 客户端
│   │   ├── index.ts                  # Axios 实例 (请求/响应拦截器)
│   │   ├── user.ts                   # 用户相关 API
│   │   └── document.ts               # 文档相关 API
│   ├── components/                   # 组件
│   │   ├── chat/                     # 对话相关组件
│   │   │   ├── ChatView.vue          # 对话主面板
│   │   │   ├── MessageBubble.vue     # 消息气泡
│   │   │   ├── CitationCard.vue      # 文献引用卡片
│   │   │   ├── CitationSummary.vue   # 引用汇总
│   │   │   ├── PdfViewer.vue         # PDF 查看器
│   │   │   └── RightPanel.vue        # 右侧信息面板
│   │   ├── common/                   # 通用组件
│   │   │   ├── AppLogo.vue           # 应用 Logo
│   │   │   ├── LoadingSpinner.vue    # 加载动画
│   │   │   └── ToastContainer.vue    # 消息提示容器
│   │   ├── layout/                   # 布局组件
│   │   │   ├── AppLayout.vue         # 主布局（顶栏 + 侧栏 + 内容区）
│   │   │   └── Sidebar.vue           # 侧栏导航
│   │   └── admin/                    # 管理组件
│   │       └── UserManagement.vue    # 用户管理
│   ├── composables/                  # 组合式函数
│   │   ├── useAuth.ts                # 认证逻辑
│   │   ├── useSSE.ts                 # SSE 流式连接
│   │   └── useMarkdown.ts            # Markdown 渲染
│   ├── stores/                       # Pinia 状态管理
│   │   ├── auth.ts                   # 认证状态
│   │   └── toast.ts                  # 消息提示状态
│   ├── types/                        # TypeScript 类型定义
│   │   ├── index.ts                  # 通用类型
│   │   ├── chat.ts                   # 对话相关类型
│   │   ├── user.ts                   # 用户相关类型
│   │   └── auth.ts                   # 认证相关类型
│   ├── views/                        # 页面视图
│   │   ├── ChatView.vue              # 对话页面
│   │   └── UserManagementView.vue    # 用户管理页面
│   ├── App.vue                       # 根组件
│   └── main.ts                       # 应用入口
├── index.html
├── vite.config.ts                    # Vite 配置 (含 API 代理)
├── tsconfig.json                     # TypeScript 配置
├── tailwind.config.js                # Tailwind CSS 配置
├── postcss.config.js                 # PostCSS 配置
├── env.d.ts                          # 环境类型声明
├── skills-lock.json                  # Skills 锁定
├── package.json
└── README.md                         # 本文件
```

---

## 🚀 快速开始

### 前置条件

- Node.js ≥ 18
- npm ≥ 9
- 后端 API 服务已启动（参见 [backend/README.md](../backend/README.md)）

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 配置 API 代理

`vite.config.ts` 中已配置开发代理：

```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',  // 后端 API 地址
        changeOrigin: true,
      },
    },
  },
})
```

如果后端端口或地址不同，修改 `target` 即可。

### 3. 启动开发服务器

```bash
npm run dev
```

默认运行在 `http://localhost:5173`，API 请求自动代理到 `http://localhost:8000`。

### 4. 构建生产版本

```bash
npm run build
```

构建产物输出到 `dist/` 目录，可直接部署到 Nginx 等静态服务器。

预览构建结果：

```bash
npm run preview
```

---

## 🖥️ 功能模块说明

### 对话界面 (`ChatView.vue`)

- 输入框支持 Enter 发送，Shift+Enter 换行
- 消息以气泡形式展示，用户消息和 AI 回复左右区分
- 流式 SSE 连接，实时显示 AI 逐字输出
- 支持中断流式响应

### 文献引用 (`CitationCard.vue` / `CitationSummary.vue`)

- LLM 回答中的 `[N]` 标记自动渲染为可点击引用
- 点击引用卡片展示文献标题、摘要、来源
- 引用汇总面板列出本次回答涉及的所有文献

### PDF 预览 (`PdfViewer.vue`)

- 基于 pdfjs-dist 的内嵌 PDF 查看器
- 通过后端代理接口 `/api/v1/documents/{doc_id}/pdf/stream` 获取 PDF，避免前端直连 MinIO 的 CORS 问题
- 支持翻页、缩放
- 可从引用卡片跳转到指定页面

### 用户认证

- JWT 登录，Token 存储在 localStorage
- Axios 拦截器自动在请求头添加 `Authorization: Bearer <token>`
- 401 响应自动尝试 Token 刷新（refresh token），刷新失败跳转登录页
- 支持并发请求场景：Token 刷新期间其他 401 请求进入等待队列，刷新成功后统一重试

### 用户管理 (`UserManagement.vue`)

- 管理员面板，查看和管理用户账号
- 支持添加、禁用、删除用户
- 基于角色权限控制

### 布局 (`AppLayout.vue`)

- 左侧可折叠导航侧栏
- 顶栏显示当前页面标题
- 移动端点击遮罩层自动收起侧栏
- ESC 快捷键收起侧栏

---

## 🔌 API 对接说明

### Axios 实例 (`api/index.ts`)

所有 API 请求通过统一的 Axios 实例发出：

```typescript
import api from '@/api'

// GET 请求
const res = await api.get('/v1/documents', { params: { page: 1 } })

// POST 请求
const res = await api.post('/v1/chat', { query: '高血压用药', top_k: 10 })

// 文件上传
const form = new FormData()
form.append('file', file)
await api.post('/v1/documents/upload', form, {
  headers: { 'Content-Type': 'multipart/form-data' },
})

// PDF 预览（后端代理 URL，直接传给 PdfViewer 组件）
import { fetchDocumentPdfStreamUrl } from '@/api/document'
const pdfUrl = fetchDocumentPdfStreamUrl(docId)  // → /api/v1/documents/{docId}/pdf/stream
```

### SSE 流式连接 (`useSSE.ts`)

对话流式回答使用 EventSource + fetch ReadableStream：

```typescript
import { useSSE } from '@/composables/useSSE'

const { connect, disconnect } = useSSE({
  url: '/api/v1/chat/stream',
  onMessage: (data) => {
    // 处理每个 token
    console.log(data.token)
  },
  onDone: () => {
    // 流式输出完成
  },
  onError: (err) => {
    // 处理错误
  },
})

connect({ query: '高血压用药', top_k: 10 })
// 不需要时断开
// disconnect()
```

---

## 🧩 组件概览

### Chat 组件

| 组件名               | 功能                             |
| -------------------- | -------------------------------- |
| `ChatView.vue`       | 对话主面板，消息列表 + 输入区    |
| `MessageBubble.vue`  | 单条消息气泡（用户/AI 区分）     |
| `CitationCard.vue`   | 单条文献引用卡片                 |
| `CitationSummary.vue`| 引用来源汇总列表                 |
| `PdfViewer.vue`      | 内嵌 PDF 查看器（后端代理模式）  |
| `RightPanel.vue`     | 右侧信息面板（引用/PDF）        |

### 通用组件

| 组件名                | 功能                     |
| --------------------- | ------------------------ |
| `AppLogo.vue`         | 应用品牌 Logo            |
| `LoadingSpinner.vue`  | 加载动画指示器           |
| `ToastContainer.vue`  | 全局消息提示（成功/错误/信息） |

### 布局组件

| 组件名           | 功能                           |
| ---------------- | ------------------------------ |
| `AppLayout.vue`  | 主布局框架（顶栏 + 侧栏 + 内容）|
| `Sidebar.vue`    | 导航侧栏                       |

---

## 🎨 样式与主题

- 使用 **Tailwind CSS** 原子化样式
- 主色调基于 slate/blue 色系
- 毛玻璃效果（`backdrop-blur-xl`）的顶栏
- 响应式断点：移动端侧栏全屏遮罩，桌面端侧栏固定
- 所有组件均带过渡动画（`transition-all duration-300`）

---

## 📝 开发说明

### 添加新页面

1. 在 `src/views/` 下创建 `.vue` 文件
2. 在路由配置中添加对应路由
3. 在侧栏组件 `Sidebar.vue` 中添加导航项

### 添加新 API

1. 在 `src/api/` 下创建对应模块文件
2. 使用 `api/index.ts` 中导出的 Axios 实例
3. 在 `src/types/` 下定义请求/响应类型

### 类型定义

类型文件集中在 `src/types/`：

| 文件         | 内容                         |
| ------------ | ---------------------------- |
| `index.ts`   | 通用类型（分页、API 响应等）|
| `chat.ts`    | 消息、对话、引用类型        |
| `user.ts`    | 用户数据类型                |
| `auth.ts`    | 登录/注册/Token 类型        |

### 构建与部署

```bash
# 构建
npm run build

# 输出目录：dist/
# 部署时需将 /api 路径代理到后端服务
```

Nginx 配置示例：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /path/to/dist;
    index index.html;

    # API 代理
    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # SPA 路由回退
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

## 🐛 常见问题

**页面白屏 / 路由无法访问？**
确认后端 API 已启动，且 `.env` 中的 API 地址配置正确。检查浏览器控制台是否有网络请求错误。

**登录后马上跳回登录页？**
Token 可能已过期。确认后端 `/api/v1/auth/refresh` 接口可用。检查 localStorage 中的 `access_token` 和 `refresh_token`。

**流式输出卡住？**
确认后端 SSE 接口正常返回 `text/event-stream` 响应头。检查网络是否关闭了缓冲（如 Nginx 的 `proxy_buffering off`）。

**API 请求 401？**
检查 Token 是否有效。Axios 拦截器会自动尝试刷新 Token，但如果 refresh token 也过期了，需要重新登录。
