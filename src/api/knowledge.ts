import api from './index'
import type { Document } from '@/types'

export function fetchDocumentsApi(): Promise<Document[]> {
  return api.get('/knowledge/documents').then((res) => res.data)
}

export function uploadDocumentApi(file: File): Promise<Document> {
  const formData = new FormData()
  formData.append('file', file)
  return api
    .post('/knowledge/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data)
}

export function deleteDocumentApi(id: string): Promise<void> {
  return api.delete(`/knowledge/documents/${id}`).then((res) => res.data)
}
