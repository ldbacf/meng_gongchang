import api from './index'
import type { KnowledgeBase, DocumentInfo, KBCreatePayload } from '@/types/knowledge'

// ── Knowledge Bases ──

export async function fetchKnowledgeBasesApi(): Promise<KnowledgeBase[]> {
  return api.get('/v1/admin/knowledge-bases').then((res) => res.data)
}

export async function createKnowledgeBaseApi(payload: KBCreatePayload): Promise<KnowledgeBase> {
  return api.post('/v1/admin/knowledge-bases', payload).then((res) => res.data)
}

export async function deleteKnowledgeBaseApi(id: string): Promise<void> {
  return api.delete(`/v1/admin/knowledge-bases/${id}`)
}

// ── Documents (KB-scoped) ──

export async function fetchDocumentsApi(kbId: string): Promise<DocumentInfo[]> {
  return api.get(`/v1/admin/knowledge-bases/${kbId}/documents`).then((res) => res.data)
}

export async function uploadDocumentApi(kbId: string, file: File): Promise<DocumentInfo> {
  const formData = new FormData()
  formData.append('file', file)
  return api
    .post(`/v1/admin/knowledge-bases/${kbId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data)
}

export async function deleteDocumentApi(id: string): Promise<void> {
  return api.delete(`/v1/admin/documents/${id}`)
}

export async function retryDocumentApi(id: string): Promise<{ ok: boolean; retry_from: string }> {
  return api.post(`/v1/admin/documents/${id}/retry`).then((res) => res.data)
}
