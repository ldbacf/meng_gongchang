import api from './index'
import type { Document } from '@/types'

export async function fetchDocumentsApi(): Promise<Document[]> {
  return api.get('/v1/admin/documents').then((res) =>
    (res.data as any[]).map((d: any) => ({
      id: d.id,
      name: d.original_name,
      size: 0,
      status: mapDocStatus(d.status),
      progress: d.status === 'parsed' ? 100 : 50,
      chunks: undefined,
      uploadedAt: d.created_at ? new Date(d.created_at).getTime() : Date.now(),
    })),
  )
}

function mapDocStatus(s: string): Document['status'] {
  switch (s) {
    case 'pending': return 'uploading'
    case 'processing': return 'chunking'
    case 'parsed': return 'ready'
    case 'failed': return 'error'
    default: return 'uploading'
  }
}

export async function uploadDocumentApi(file: File): Promise<Document> {
  const formData = new FormData()
  formData.append('file', file)
  return api
    .post('/v1/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => {
      const d = res.data
      return {
        id: d.id,
        name: d.original_name ?? file.name,
        size: file.size,
        status: 'uploading' as const,
        progress: 50,
        uploadedAt: Date.now(),
      }
    })
}

export async function deleteDocumentApi(id: string): Promise<void> {
  return api.delete(`/v1/admin/documents/${id}`)
}
