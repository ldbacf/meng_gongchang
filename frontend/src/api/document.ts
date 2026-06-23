import api from './index'

export interface DocumentPdfResponse {
  pdf_url: string
  total_pages: number
}

export async function fetchDocumentPdfApi(docId: string): Promise<DocumentPdfResponse> {
  const res = await api.get<{ pdf_url: string; total_pages: number }>(
    `/v1/documents/${docId}/pdf`,
  )
  return {
    pdf_url: res.data.pdf_url,
    total_pages: res.data.total_pages ?? 0,
  }
}

/** 返回后端代理 PDF 流的 URL（避免前端直连 MinIO 的 CORS 问题） */
export function fetchDocumentPdfStreamUrl(docId: string): string {
  return `/api/v1/documents/${docId}/pdf/stream`
}
