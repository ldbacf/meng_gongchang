import { USE_MOCK, simulateDelay } from '@/mock'

export interface DocumentPdfResponse {
  pdfUrl: string
  totalPages: number
}

const docPdfMap: Record<string, DocumentPdfResponse> = {
  'doc-001': {
    pdfUrl: '/pdf/基层全科医生心血管疾病风险评估与沟通策略.pdf',
    totalPages: 86,
  },
  'doc-002': {
    pdfUrl: '/pdf/慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究.pdf',
    totalPages: 112,
  },
  'doc-003': {
    pdfUrl: '/pdf/我国基层卫生服务与管理评价指标体系研究进展.pdf',
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
  // Real API call (when backend is ready)
  // return fetch(`/api/knowledge/documents/${docId}/pdf`).then(res => res.json())
  throw new Error('Real API not configured')
}
