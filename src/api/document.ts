import { USE_MOCK, simulateDelay } from '@/mock'

export interface DocumentPdfResponse {
  pdfUrl: string
  totalPages: number
}

const docPdfMap: Record<string, DocumentPdfResponse> = {
  'doc-001': {
    pdfUrl: '/api/pdf/1',
    totalPages: 86,
  },
  'doc-002': {
    pdfUrl: '/api/pdf/2',
    totalPages: 112,
  },
  'doc-003': {
    pdfUrl: '/api/pdf/3',
    totalPages: 65,
  },
}

export async function fetchDocumentPdfApi(docId: string): Promise<DocumentPdfResponse> {
  if (USE_MOCK) {
    await simulateDelay(300)
    const result = docPdfMap[docId]
    if (!result) {
      throw new Error(`Document not found: ${docId}`)
    }
    return { ...result }
  }
  const res = await fetch(`/api/knowledge/documents/${docId}/pdf`)
  if (!res.ok) throw new Error(`Failed to fetch PDF info: ${res.status}`)
  return res.json()
}
