export interface Citation {
  id: string
  title: string
  source: string
  snippet: string
  url?: string
  page?: number
}

export interface Message {
  id: string
  role: 'user' | 'ai'
  content: string
  citations?: Citation[]
  timestamp: number
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
