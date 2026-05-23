export interface DocumentPdfResponse {
  pdf_url: string
  total_pages: number
}

export async function fetchDocumentPdfApi(docId: string): Promise<DocumentPdfResponse> {
  const token = localStorage.getItem('access_token')
  const res = await fetch(`/api/v1/documents/${docId}/pdf`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
  if (!res.ok) throw new Error(`Failed to fetch PDF info: ${res.status}`)
  const data = await res.json()
  return {
    pdf_url: data.pdf_url,
    total_pages: data.total_pages ?? 0,
  }
}
