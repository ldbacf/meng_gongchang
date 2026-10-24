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
  /**
   * 后端实际写的是 `"done"`（`build_rag_step` 的默认值），而 SSE 的 `s` 字段也是
   * `"done"`；早期前端把它映射成了 `"completed"`。落库回放时拿到的是原始 `"done"`，
   * 只认 `"completed"` 会导致勾选态丢失（表现为空心圈、点不开）。两者都接受。
   */
  status: 'pending' | 'done' | 'completed' | 'failed'
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

/**
 * SSE `cite` 帧里的一条引用。
 *
 * 后端 `frame_cite(citations: list)` 一次发整组（`{t:'cite', citations:[...]}`），
 * 不是一条一帧。字段与落库的 Citation 同形，`idx` 是正文里的展示序号（"1".."5"）。
 */
export interface CitationFrame {
  idx: string | number
  doc_id?: string | null
  title: string
  source?: string
  snippet: string
  md5?: string
  relevance?: number
}

export type SSEMessage =
  | { t: 'step'; k: 'intent' | 'retrieval' | 'fusion' | 'answer'; s: 'pending' | 'done'; title: string; elapsed_ms?: number; summary?: string; metrics?: RagStepMetrics }
  | { t: 'text'; c: string }
  | { t: 'cite'; citations: CitationFrame[] }
  | { t: 'done'; conversation_id: string; message_id: string }
  | { t: 'error'; message: string }
  | { t: 'heartbeat' }

