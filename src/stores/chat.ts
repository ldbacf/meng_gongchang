import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation, Message, Citation, RagSteps, SSEMessage } from '@/types'
import { fetchConversationsApi, createConversationApi, fetchMessagesApi, deleteConversationApi, renameConversationApi } from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const streamContent = ref('')
  const streamCitations = ref<Citation[]>([])
  const streamRagSteps = ref<RagSteps>({})
  const streamError = ref<string | null>(null)

  // ── Character-by-character reveal ──
  const displayedLength = ref(0)
  let _revealTimer: ReturnType<typeof setInterval> | null = null

  const revealedContent = computed(() =>
    streamContent.value.slice(0, displayedLength.value),
  )
  const streamComplete = ref(false)
  let _pendingFinish: { messageId?: string; ragSteps?: RagSteps } | null = null

  const currentConversation = computed(() =>
    conversations.value.find((c) => c.id === currentConversationId.value),
  )

  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  )

  // ── actions ──

  async function fetchConversations() {
    try {
      conversations.value = await fetchConversationsApi()
    } catch {
      // Keep current state on API failure
    }
  }

  async function createConversation(title?: string): Promise<string> {
    const conv = await createConversationApi(title)
    conversations.value.unshift(conv)
    currentConversationId.value = conv.id
    messages.value = []
    return conv.id
  }

  async function selectConversation(id: string) {
    currentConversationId.value = id
    try {
      messages.value = await fetchMessagesApi(id)
    } catch {
      messages.value = []
    }
    if (!conversations.value.find((c) => c.id === id)) {
      conversations.value.unshift({
        id,
        title: '对话',
        updatedAt: Date.now(),
      })
    }
  }

  async function deleteConversation(id: string) {
    try {
      await deleteConversationApi(id)
    } catch {}
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      messages.value = []
    }
  }

  async function renameConversation(id: string, title: string) {
    try {
      await renameConversationApi(id, title)
    } catch { return }
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) {
      conv.title = title
      conv.updatedAt = Date.now()
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
    const conv = conversations.value.find((c) => c.id === currentConversationId.value)
    if (conv) {
      conv.updatedAt = Date.now()
    }
  }

  function startStreaming() {
    _pendingFinish = null
    streamComplete.value = false
    isStreaming.value = true
    streamContent.value = ''
    streamCitations.value = []
    streamRagSteps.value = {}
    streamError.value = null
    displayedLength.value = 0
    _startReveal()
  }

  function appendStreamContent(text: string) {
    streamContent.value += text
  }

  function addStreamCitation(citation: Citation) {
    streamCitations.value.push(citation)
  }

  function finishStreaming(messageId?: string, ragSteps?: RagSteps) {
    if (displayedLength.value >= streamContent.value.length) {
      _doFinishStreaming(messageId, ragSteps)
      return
    }
    _pendingFinish = { messageId, ragSteps }
    streamComplete.value = true
  }

  function _doFinishStreaming(messageId?: string, ragSteps?: RagSteps) {
    _stopReveal()
    displayedLength.value = streamContent.value.length

    const msg: Message = {
      id: messageId ?? crypto.randomUUID(),
      role: 'ai',
      content: streamContent.value,
      citations: [...streamCitations.value],
      ragSteps: ragSteps ?? undefined,
      timestamp: Date.now(),
    }
    messages.value.push(msg)

    isStreaming.value = false
    streamContent.value = ''
    streamCitations.value = []
    streamRagSteps.value = {}

    const conv = conversations.value.find((c) => c.id === currentConversationId.value)
    if (conv) {
      conv.updatedAt = Date.now()
    }
    fetchConversations()
  }

  function _finalizeStream() {
    const p = _pendingFinish
    _pendingFinish = null
    streamComplete.value = false
    _doFinishStreaming(p?.messageId, p?.ragSteps)
  }

  function handleStreamMsg(msg: SSEMessage) {
    switch (msg.t) {
      case 'step':
        streamRagSteps.value = {
          ...streamRagSteps.value,
          [msg.k]: {
            status: msg.s === 'done' ? 'completed' : 'pending',
            title: msg.title,
            summary: msg.summary,
            elapsed_ms: msg.elapsed_ms,
            metrics: msg.metrics,
          },
        }
        break
      case 'text':
        appendStreamContent(msg.c)
        break
      case 'cite':
        addStreamCitation({
          id: msg.id,
          title: msg.title,
          source: msg.source,
          snippet: msg.snippet,
          page: msg.page,
          doc_id: msg.doc_id,
          relevance: msg.relevance,
        })
        break
      case 'done':
        finishStreaming(msg.message_id, { ...streamRagSteps.value })
        break
      case 'error':
        _pendingFinish = null
        streamComplete.value = false
        _stopReveal()
        streamError.value = msg.message
        isStreaming.value = false
        break
    }
  }

  // ── Reveal helpers ──

  function _startReveal() {
    _stopReveal()
    _revealTimer = setInterval(() => {
      if (displayedLength.value < streamContent.value.length) {
        displayedLength.value = Math.min(
          displayedLength.value + 3,
          streamContent.value.length,
        )
      }
      if (streamComplete.value && displayedLength.value >= streamContent.value.length) {
        _stopReveal()
        _finalizeStream()
      }
    }, 50)
  }

  function _stopReveal() {
    if (_revealTimer !== null) {
      clearInterval(_revealTimer)
      _revealTimer = null
    }
  }

  return {
    conversations,
    currentConversationId,
    messages,
    isStreaming,
    streamContent,
    streamCitations,
    streamRagSteps,
    streamError,
    revealedContent,
    currentConversation,
    sortedConversations,
    fetchConversations,
    createConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    addUserMessage,
    startStreaming,
    appendStreamContent,
    addStreamCitation,
    finishStreaming,
    stopReveal: _stopReveal,
    handleStreamMsg,
  }
})
