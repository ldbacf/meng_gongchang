import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation, Message, Citation, RagSteps, SSEMessage } from '@/types'
import { normalizeStepStatus } from '@/types/step'
import {
  fetchConversationsApi,
  createConversationApi,
  fetchMessagesApi,
  deleteConversationApi,
  renameConversationApi,
} from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const conversationsLoading = ref(true)
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  /**
   * 正在流式回答的是哪个会话。
   *
   * 允许用户切走再切回来：SSE 继续跑；消息区只在「当前会话 === 正在生成的会话」
   * 时才渲染那条流式气泡。生成结束时若用户已切到别的会话，就不往 messages 里塞，
   * 等他切回来由服务端拉取（后端已落库）。
   */
  const streamingConversationId = ref<string | null>(null)
  const streamContent = ref('')
  const streamCitations = ref<Citation[]>([])
  const streamRagSteps = ref<RagSteps>({})
  const streamError = ref<string | null>(null)

  // ── Character-by-character reveal ──
  const displayedLength = ref(0)
  let _revealTimer: ReturnType<typeof setInterval> | null = null

  const revealedContent = computed(() => streamContent.value.slice(0, displayedLength.value))
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
    } finally {
      conversationsLoading.value = false
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
    // 删除失败时必须保留本地条目：以前这里是空 catch，服务端还在、前端却已从
    // 列表里抹掉，用户刷新后「删掉的会话又回来了」，且全程没有任何提示。
    try {
      await deleteConversationApi(id)
    } catch (e) {
      console.error('删除会话失败:', e)
      throw e
    }
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      messages.value = []
    }
  }

  async function renameConversation(id: string, title: string) {
    try {
      await renameConversationApi(id, title)
    } catch {
      return
    }
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

  /** 本地移除一条消息（「重新生成」时先撤下旧回答；服务端会在新回答落库时删除它） */
  function removeMessage(id: string) {
    const i = messages.value.findIndex((m) => m.id === id)
    if (i >= 0) messages.value.splice(i, 1)
  }

  function startStreaming() {
    _pendingFinish = null
    streamComplete.value = false
    isStreaming.value = true
    streamingConversationId.value = currentConversationId.value
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
    // 用户可能已经切到别的会话：此时不要把这条消息塞进别人的 messages，
    // 切回来时由 selectConversation 从服务端拉（persist 节点已落库）。
    if (streamingConversationId.value === currentConversationId.value) {
      messages.value.push(msg)
    }

    isStreaming.value = false
    streamingConversationId.value = null
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
            // 直接用后端的规范值（`done`），不再映射成 `completed` ——
            // 那层映射正是"历史会话回放丢失勾选态"的根因。
            status: normalizeStepStatus(msg.s),
            title: msg.title,
            summary: msg.summary,
            elapsed_ms: msg.elapsed_ms,
            // metrics 的取舍（三种情况，别混）：
            //   1. `done`：完整 metrics（top_scores/keywords 等全字段）
            //   2. `pending` + `live: true`：**实时进度**，只带已得的计数字段
            //      （后端 retrieval 在 embed/milvus/每批 es 各发一帧，fusion 在
            //       rrf 后与 rerank 后各发一帧）。这是「已召回 N 篇」的数据源。
            //   3. `pending` 且非 live：后端 `frame_step` 给的是 `{}`。空对象 truthy，
            //      会让 `v-if="...metrics"` 放行并渲染尚未产出的字段
            //      （top_scores/keywords）→ undefined.length 打崩 vdom。
            //      故置 undefined，符合模板 `metrics?:` 的可选契约。
            metrics:
              msg.s === 'done'
                ? msg.metrics
                : (msg.metrics as { live?: boolean } | undefined)?.live
                  ? msg.metrics
                  : undefined,
          },
        }
        break
      case 'text':
        appendStreamContent(msg.c)
        break
      case 'cite':
        // 后端一次发整组（{t:'cite', citations:[...]}），不是一条一帧。
        // 曾按单对象读 msg.id/msg.title → 推入一条全 undefined 的引用：
        // 「参考文献 · 1」且 citation.doc_id 为空 → 点开 PDF 无反应。
        for (const c of msg.citations ?? []) {
          addStreamCitation({
            id: String(c.idx),
            title: c.title ?? '',
            source: c.source ?? '',
            snippet: c.snippet ?? '',
            doc_id: c.doc_id ?? undefined,
            relevance: c.relevance ?? 0,
          })
        }
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
        streamingConversationId.value = null
        break
    }
  }

  // ── Reveal helpers ──

  function _startReveal() {
    _stopReveal()
    // 100ms/步、每步 6 字：观感与 50ms/3 字接近，但整段 markdown 的重解析次数减半。
    // 每次 tick 都会让 AiMessage 的 renderedContent 重算 → md.render() 全文重解析 →
    // v-html 整体替换 innerHTML，代价不低（详见 AiMessage.vue 注释）。
    _revealTimer = setInterval(() => {
      if (displayedLength.value < streamContent.value.length) {
        displayedLength.value = Math.min(displayedLength.value + 6, streamContent.value.length)
      }
      if (streamComplete.value && displayedLength.value >= streamContent.value.length) {
        _stopReveal()
        _finalizeStream()
      }
    }, 100)
  }

  function _stopReveal() {
    if (_revealTimer !== null) {
      clearInterval(_revealTimer)
      _revealTimer = null
    }
  }

  return {
    conversations,
    conversationsLoading,
    currentConversationId,
    messages,
    isStreaming,
    streamingConversationId,
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
    removeMessage,
    startStreaming,
    appendStreamContent,
    addStreamCitation,
    finishStreaming,
    stopReveal: _stopReveal,
    handleStreamMsg,
  }
})
