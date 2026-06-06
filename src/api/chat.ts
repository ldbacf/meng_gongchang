import api from './index'
import type { Conversation, Message } from '@/types'

export async function fetchConversationsApi(): Promise<Conversation[]> {
  const res = await api.get('/v1/conversations')
  return (res.data as any[]).map((c: any) => ({
    id: c.id,
    title: c.title,
    updatedAt: new Date(c.updated_at).getTime(),
  }))
}

export async function createConversationApi(title?: string): Promise<Conversation> {
  const res = await api.post('/v1/conversations', { title: title ?? '新对话' })
  const c = res.data
  return {
    id: c.id,
    title: c.title,
    updatedAt: new Date(c.updated_at).getTime(),
  }
}

export async function renameConversationApi(id: string, title: string): Promise<void> {
  return api.patch(`/v1/conversations/${id}`, { title })
}

export async function fetchMessagesApi(conversationId: string): Promise<Message[]> {
  const res = await api.get(`/v1/conversations/${conversationId}/messages`)
  return (res.data as any[]).map((m: any) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations ?? [],
    ragSteps: mapRagSteps(m.rag_steps),
    timestamp: new Date(m.created_at).getTime(),
  }))
}

function mapRagSteps(steps: Record<string, any> | null | undefined) {
  if (!steps) return undefined
  const result: Record<string, any> = {}
  for (const [key, val] of Object.entries(steps)) {
    result[key] = { ...val }
  }
  return result
}

export async function deleteConversationApi(id: string): Promise<void> {
  return api.delete(`/v1/conversations/${id}`)
}
