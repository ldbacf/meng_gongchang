export interface Citation {
  id: string
  title: string
  source: string
  snippet: string
  url?: string
  page?: number
  pdfUrl?: string
  doc_id?: string
  relevance?: number
}

// ── RAG Pipeline Metrics ──

export interface IntentMetrics {
  domain: string
  coverage: 'high' | 'medium' | 'low' | 'out_of_domain' | 'unknown'
  rewritten_query: string
  keywords: string[]
  suggestion: string
}

export interface DocRef {
  title: string
  score: number
}

export interface RetrievalMetrics {
  milvus_hits: number
  es_hits: number
  after_dedup: number
  routing: 'both' | 'milvus_only' | 'es_only'
  milvus_top_docs: DocRef[]
  es_top_docs: DocRef[]
  overlap: number
}

export interface FusionMetrics {
  input_count: number
  output_count: number
  model: string
  top_scores: number[]
}

export interface AnswerMetrics {
  model: string
  context_chunks: number
  total_tokens: number
  total_elapsed_ms: number
}

export type RagStepMetrics = IntentMetrics | RetrievalMetrics | FusionMetrics | AnswerMetrics

export interface RagStep {
  status: 'pending' | 'completed'
  title: string
  summary?: string
  elapsed_ms?: number
  metrics?: RagStepMetrics
}

export interface RagSteps {
  intent?: RagStep
  retrieval?: RagStep
  fusion?: RagStep
  answer?: RagStep
}

export interface Message {
  id: string
  role: 'user' | 'ai'
  content: string
  citations?: Citation[]
  timestamp: number
  ragSteps?: RagSteps
}

export interface Conversation {
  id: string
  title: string
  updatedAt: number
}

// ── Single-line SSE message types ──

export type SSEMessage =
  | { t: 'step'; k: 'intent' | 'retrieval' | 'fusion' | 'answer'; s: 'pending' | 'done'; title: string; elapsed_ms?: number; summary?: string; metrics?: RagStepMetrics }
  | { t: 'text'; c: string }
  | { t: 'cite'; id: string; title: string; source: string; snippet: string; page?: number; doc_id?: string; relevance?: number }
  | { t: 'done'; conversation_id: string; message_id: string }
  | { t: 'error'; message: string }

