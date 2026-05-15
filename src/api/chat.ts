import api from './index'
import type { Conversation, Message } from '@/types'

export function fetchConversationsApi(): Promise<Conversation[]> {
  return api.get('/conversations').then((res) => res.data)
}

export function fetchMessagesApi(conversationId: string): Promise<Message[]> {
  return api.get(`/conversations/${conversationId}/messages`).then((res) => res.data)
}

export function deleteConversationApi(id: string): Promise<void> {
  return api.delete(`/conversations/${id}`).then((res) => res.data)
}
