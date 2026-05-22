import api from './index'
import type { Conversation, Message } from '@/types'
import { USE_MOCK, mockConversations, mockMessages, simulateDelay } from '@/mock'

export async function fetchConversationsApi(): Promise<Conversation[]> {
  if (USE_MOCK) {
    await simulateDelay(150)
    return [...mockConversations]
  }
  return api.get('/conversations').then((res) => res.data)
}

export async function fetchMessagesApi(conversationId: string): Promise<Message[]> {
  if (USE_MOCK) {
    await simulateDelay(150)
    return mockMessages[conversationId] ? [...mockMessages[conversationId]] : []
  }
  return api.get(`/conversations/${conversationId}/messages`).then((res) => res.data)
}

export async function deleteConversationApi(id: string): Promise<void> {
  if (USE_MOCK) {
    await simulateDelay(100)
    return
  }
  return api.delete(`/conversations/${id}`).then((res) => res.data)
}
