export type DocumentStatus =
  | 'uploading'
  | 'chunking'
  | 'embedding'
  | 'ready'
  | 'error'

export interface Document {
  id: string
  name: string
  size: number
  status: DocumentStatus
  progress: number
  chunks?: number
  uploadedAt: number
}
