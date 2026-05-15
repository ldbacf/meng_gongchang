import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation, Message, Citation } from '@/types'
import { fetchConversationsApi, fetchMessagesApi, deleteConversationApi } from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const streamContent = ref('')
  const streamCitations = ref<Citation[]>([])

  const currentConversation = computed(() =>
    conversations.value.find((c) => c.id === currentConversationId.value),
  )

  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  )

  async function fetchConversations() {
    try {
      conversations.value = await fetchConversationsApi()
    } catch {
      conversations.value = []
    }
  }

  async function createConversation(title?: string): Promise<string> {
    const id = crypto.randomUUID()
    const now = Date.now()
    const conv: Conversation = {
      id,
      title: title ?? '新对话',
      updatedAt: now,
    }
    conversations.value.unshift(conv)
    currentConversationId.value = id
    messages.value = []
    return id
  }

  async function selectConversation(id: string) {
    currentConversationId.value = id
    messages.value = []
    try {
      messages.value = await fetchMessagesApi(id)
    } catch {
      messages.value = []
    }
  }

  async function deleteConversation(id: string) {
    try {
      await deleteConversationApi(id)
    } catch {
      // Proceed with local deletion regardless
    }
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      messages.value = []
    }
  }

  function addUserMessage(content: string) {
    const msg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: Date.now(),
    }
    messages.value.push(msg)
  }

  function startStreaming() {
    isStreaming.value = true
    streamContent.value = ''
    streamCitations.value = []
  }

  function appendStreamContent(text: string) {
    streamContent.value += text
  }

  function addStreamCitation(citation: Citation) {
    streamCitations.value.push(citation)
  }

  function finishStreaming(messageId?: string) {
    const msg: Message = {
      id: messageId ?? crypto.randomUUID(),
      role: 'ai',
      content: streamContent.value,
      citations: [...streamCitations.value],
      timestamp: Date.now(),
    }
    messages.value.push(msg)

    isStreaming.value = false
    streamContent.value = ''
    streamCitations.value = []

    // Update conversation title from first message if untitled
    if (
      currentConversationId.value &&
      messages.value.length === 2
    ) {
      const conv = conversations.value.find(
        (c) => c.id === currentConversationId.value,
      )
      if (conv && conv.title === '新对话') {
        const userMsg = messages.value[0]?.content ?? ''
        conv.title = userMsg.slice(0, 30) + (userMsg.length > 30 ? '...' : '')
      }
    }
  }

  return {
    conversations,
    currentConversationId,
    messages,
    isStreaming,
    streamContent,
    streamCitations,
    currentConversation,
    sortedConversations,
    fetchConversations,
    createConversation,
    selectConversation,
    deleteConversation,
    addUserMessage,
    startStreaming,
    appendStreamContent,
    addStreamCitation,
    finishStreaming,
  }
})
