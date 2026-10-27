import type { StepStatus } from './step'

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

/**
 * 实时进度帧（`live: true`）。
 *
 * 与上面三种「完成态 metrics」不是一回事：完成态字段齐全，而进度帧只带
 * **当前已得**的计数（retrieval 会在 embed / milvus / 每批 es 各发一帧）。
 * 前端据此显示「已召回 12 篇」——数字真实，不是估算。
 *
 * 单独建模而不复用 `RetrievalMetrics`：后者字段必填，进度帧里 `routing`、
 * `*_top_docs` 都还不存在，混用会让类型检查失去意义。
 */
export interface LiveProgressMetrics {
  live: true
  stage?: 'embed' | 'milvus' | 'es' | 'rerank' | 'done' | ''
  milvus_hits?: number
  es_hits?: number
  /** 两路已取回的原始条数（未去重，必然大于真实命中数） */
  fetched?: number
  after_dedup?: number
  es_total?: number
  input_count?: number
  output_count?: number
}

export type RagStepMetrics =
  | IntentMetrics
  | RetrievalMetrics
  | FusionMetrics
  | AnswerMetrics
  | LiveProgressMetrics

export interface RagStep {
  /** 与后端 `app/domain/lifecycle.py` 同一枚举；`done` 是规范成功态 */
  status: StepStatus
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

