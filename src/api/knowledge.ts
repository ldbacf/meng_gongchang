import api from './index'
import type { Document } from '@/types'
import { USE_MOCK, mockDocuments, simulateDelay } from '@/mock'

export async function fetchDocumentsApi(): Promise<Document[]> {
  if (USE_MOCK) {
    await simulateDelay(150)
    return [...mockDocuments]
  }
  return api.get('/knowledge/documents').then((res) => res.data)
}

export async function uploadDocumentApi(file: File): Promise<Document> {
  if (USE_MOCK) {
    await simulateDelay(300)
    const doc: Document = {
      id: `doc-${crypto.randomUUID().slice(0, 8)}`,
      name: file.name,
      size: file.size,
      status: 'ready',
      progress: 100,
      chunks: Math.floor(Math.random() * 50) + 20,
      uploadedAt: Date.now(),
    }
    return doc
  }
  const formData = new FormData()
  formData.append('file', file)
  return api
    .post('/knowledge/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data)
}

export async function deleteDocumentApi(id: string): Promise<void> {
  if (USE_MOCK) {
    await simulateDelay(100)
    return
  }
  return api.delete(`/knowledge/documents/${id}`).then((res) => res.data)
}
