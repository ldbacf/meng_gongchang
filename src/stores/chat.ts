import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation, Message, Citation } from '@/types'
import { fetchMessagesApi, deleteConversationApi } from '@/api/chat'
import { mockConversations, mockMessages } from '@/mock'
import { useAuthStore } from '@/stores/auth'

// ── helpers ──

const UNTITLED_PATTERNS = ['新对话', '对话']

function isUntitled(title: string): boolean {
  return UNTITLED_PATTERNS.includes(title)
}

function summarizeTitle(content: string): string {
  return content.slice(0, 30) + (content.length > 30 ? '...' : '')
}

// ── per-user storage ──

function convsKey(username: string): string {
  return `medrag_${username}_conversations`
}

function msgsKey(username: string): string {
  return `medrag_${username}_messages`
}

function seededFlagKey(username: string): string {
  return `medrag_${username}_seeded`
}

// ── store ──

export const useChatStore = defineStore('chat', () => {
  const authStore = useAuthStore()

  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const streamContent = ref('')
  const streamCitations = ref<Citation[]>([])
  const messagesCache = new Map<string, Message[]>()

  const currentConversation = computed(() =>
    conversations.value.find((c) => c.id === currentConversationId.value),
  )

  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  )

  // ── current user ──

  function username(): string | null {
    return authStore.user?.username ?? null
  }

  // ── persistence ──

  function persistConversations() {
    const u = username()
    if (!u) return
    localStorage.setItem(convsKey(u), JSON.stringify(conversations.value))
  }

  function persistMessages() {
    const u = username()
    if (!u) return
    const obj: Record<string, Message[]> = {}
    for (const [key, msgs] of messagesCache) {
      obj[key] = msgs
    }
    localStorage.setItem(msgsKey(u), JSON.stringify(obj))
  }

  function seedIfNewUser(u: string) {
    if (localStorage.getItem(seededFlagKey(u))) return

    localStorage.setItem(convsKey(u), JSON.stringify(mockConversations))

    const obj: Record<string, Message[]> = {}
    for (const [id, msgs] of Object.entries(mockMessages)) {
      obj[id] = msgs
    }
    localStorage.setItem(msgsKey(u), JSON.stringify(obj))

    localStorage.setItem(seededFlagKey(u), '1')
  }

  function loadUserData(u: string) {
    // conversations
    try {
      const raw = localStorage.getItem(convsKey(u))
      conversations.value = raw ? JSON.parse(raw) : []
    } catch {
      conversations.value = []
    }

    // messages cache
    messagesCache.clear()
    try {
      const raw = localStorage.getItem(msgsKey(u))
      if (raw) {
        const obj = JSON.parse(raw)
        for (const [key, msgs] of Object.entries(obj)) {
          messagesCache.set(key, msgs as Message[])
        }
      }
    } catch { /* corrupted */ }
  }

  // ── actions ──

  async function fetchConversations() {
    const u = username()
    if (!u) return

    seedIfNewUser(u)
    loadUserData(u)
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
    messagesCache.set(id, [])
    persistConversations()
    persistMessages()
    return id
  }

  async function selectConversation(id: string) {
    currentConversationId.value = id

    const cached = messagesCache.get(id)
    messages.value = cached ? [...cached] : []

    if (!conversations.value.find((c) => c.id === id)) {
      conversations.value.unshift({
        id,
        title: '对话',
        updatedAt: Date.now(),
      })
      persistConversations()
    }

    try {
      const apiMessages = await fetchMessagesApi(id)
      if (apiMessages.length > 0) {
        messages.value = apiMessages
        messagesCache.set(id, [...apiMessages])
        persistMessages()
      }
    } catch {
      // Keep cached/local messages on API failure
    }
  }

  async function deleteConversation(id: string) {
    try {
      await deleteConversationApi(id)
    } catch {
      // Proceed with local deletion regardless
    }
    conversations.value = conversations.value.filter((c) => c.id !== id)
    messagesCache.delete(id)
    persistConversations()
    persistMessages()
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
    messagesCache.set(currentConversationId.value!, [...messages.value])
    persistMessages()

    const conv = conversations.value.find((c) => c.id === currentConversationId.value)
    if (conv) {
      conv.updatedAt = Date.now()
      if (isUntitled(conv.title)) {
        conv.title = summarizeTitle(content)
      }
      persistConversations()
    }
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
    messagesCache.set(currentConversationId.value!, [...messages.value])
    persistMessages()

    isStreaming.value = false
    streamContent.value = ''
    streamCitations.value = []

    const conv = conversations.value.find((c) => c.id === currentConversationId.value)
    if (conv) {
      conv.updatedAt = Date.now()
      if (isUntitled(conv.title)) {
        const userMsg = messages.value.find((m) => m.role === 'user')
        if (userMsg) {
          conv.title = summarizeTitle(userMsg.content)
        }
      }
      persistConversations()
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
