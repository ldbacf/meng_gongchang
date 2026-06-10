export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  slug: string
  es_index: string
  milvus_collection: string
  created_at: string | null
  document_count: number
  has_ready_docs: boolean
}

export interface PipelineStep {
  status: 'pending' | 'running' | 'done' | 'failed'
  ts: string
  error?: string
  chunk_count?: number
  target_index?: string
  target_collection?: string
  count?: number
}

export interface DocumentInfo {
  id: string
  original_name: string
  md5: string
  status: 'pending' | 'processing' | 'parsed' | 'indexing' | 'ready' | 'failed'
  kb_id: string | null
  pipeline_steps: Record<string, PipelineStep> | null
  created_at: string | null
  error_msg: string | null
}

export interface KBCreatePayload {
  name: string
  description: string | null
  slug: string
}
