# PDF 预览方案对比

## 当前方案（方案 B）：后端代理

```
前端 (localhost:3000)  ──→  后端 (localhost:8000)  ──→  MinIO (localhost:9000)
                        StreamingResponse            内存读取
```

2026-06-23 实施说明：

后端新增 `GET /api/v1/documents/{doc_id}/pdf/stream` 端点，从 MinIO 读取 PDF 后以 `StreamingResponse` 流式返回。前端直接请求该地址，不再经 MinIO presigned URL。

**优点：**
- 完全不依赖 MinIO CORS 配置
- 前端只和后端通信，MinIO 地址对前端不可见
- 部署灵活

**缺点：**
- PDF 流经后端，增加一跳延迟
- 后端需消耗带宽和内存

---

## 废弃方案（方案 A）：前端直连 MinIO

```
前端 (localhost:3000)  ──────────────────→  MinIO (localhost:9000)
                     直接 fetch presigned URL
```

已废弃原因：由于 IDM（Internet Download Manager）浏览器插件会拦截 PDF 类请求，且 MinIO presigned URL 的 CORS 配置与 IDM 插件冲突，改用后端代理方案彻底绕过。

---

## 涉及改动

| 文件 | 改动 |
|------|------|
| `backend/src/main.py` | 新增 `GET /api/v1/documents/{doc_id}/pdf/stream` 流代理接口 |
| `frontend/src/components/chat/ChatView.vue` | `loadPdfForCitation` 直接使用 `/api/v1/documents/{doc_id}/pdf/stream` |
| `docs/pdf-proxy-vs-direct.md` | 本文档 |
