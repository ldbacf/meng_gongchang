export interface Citation {
  id: string
  title: string
  source: string
  snippet: string
  url?: string
  page?: number
  pdfUrl?: string
}

export interface RagStep {
  status: 'pending' | 'completed'
  title: string
  summary?: string
}

export interface RagSteps {
  intent?: RagStep
  retrieval?: RagStep
  fusion?: RagStep
  evaluation?: RagStep
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

export type StreamChunkType = 'text' | 'citation' | 'done' | 'error'

export interface StreamChunk {
  type: StreamChunkType
  data: string | Citation
}

export interface ChatSendRequest {
  conversationId?: string
  message: string
}

export interface ChatSendResponse {
  conversationId: string
  messageId: string
}
