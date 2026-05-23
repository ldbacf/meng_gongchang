<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import type { Citation } from '@/types'
import { fetchDocumentPdfApi } from '@/api/document'
import { useSSE } from '@/composables/useSSE'
import { useToastStore } from '@/stores/toast'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import RightPanel from './RightPanel.vue'
import { Sparkles } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const toastStore = useToastStore()
const { startStream, abort: abortSSE } = useSSE()

const messagesContainer = ref<HTMLElement | null>(null)

const streamMessage = {
  id: 'streaming',
  role: 'ai' as const,
  content: '',
  timestamp: Date.now(),
}

const streamMessageWithRagSteps = computed(() => ({
  ...streamMessage,
  ragSteps: chatStore.streamRagSteps,
}))

// ── Right panel state ──

const rightPanelOpen = ref(false)
const activeCitation = ref<Citation | null>(null)
const pdfUrl = ref<string | null>(null)
const pdfLoading = ref(false)
const showBackButton = ref(false)

const uniqueCitations = computed(() => {
  const map = new Map<string, Citation>()
  for (const msg of chatStore.messages) {
    for (const cite of msg.citations ?? []) {
      if (!map.has(cite.id)) {
        map.set(cite.id, cite)
      }
    }
  }
  return Array.from(map.values())
})

async function loadPdfForCitation(citation: Citation) {
  activeCitation.value = citation
  rightPanelOpen.value = true
  pdfLoading.value = true
  pdfUrl.value = null

  try {
    if (citation.doc_id) {
      const res = await fetchDocumentPdfApi(citation.doc_id)
      pdfUrl.value = res.pdf_url
    } else if (citation.pdfUrl) {
      pdfUrl.value = citation.pdfUrl
    }
  } catch {
    pdfUrl.value = citation.pdfUrl ?? null
  } finally {
    pdfLoading.value = false
  }
}

async function handleCitationClick(citationId: string) {
  showBackButton.value = false
  const citation = uniqueCitations.value.find((c) => c.id === citationId)
  if (citation) {
    await loadPdfForCitation(citation)
  }
}

function showCitationList() {
  showBackButton.value = true
  activeCitation.value = null
  pdfUrl.value = null
  rightPanelOpen.value = true
}

function closeRightPanel() {
  rightPanelOpen.value = false
  activeCitation.value = null
  pdfUrl.value = null
}

function goBackToList() {
  activeCitation.value = null
  pdfUrl.value = null
}

function handlePanelSelectCitation(citation: Citation) {
  showBackButton.value = true
  loadPdfForCitation(citation)
}

// ── Lifecycle ──

onMounted(async () => {
  await chatStore.fetchConversations()

  const convId = route.params.id as string | undefined
  if (convId) {
    chatStore.selectConversation(convId)
  }
})

onUnmounted(() => {
  abortSSE()
})

function abortStreaming() {
  abortSSE()
  if (chatStore.isStreaming) {
    chatStore.stopReveal()
    chatStore.isStreaming = false
    chatStore.streamContent = ''
    chatStore.streamCitations = []
  }
}

watch(
  () => route.params.id,
  async (newId) => {
    abortStreaming()
    if (newId && typeof newId === 'string') {
      if (chatStore.currentConversationId !== newId) {
        chatStore.selectConversation(newId)
      }
    } else {
      chatStore.currentConversationId = null
      chatStore.messages = []
    }
  },
)

// Sync URL after lazy conversation creation
watch(
  () => chatStore.isStreaming,
  (streaming) => {
    if (!streaming && chatStore.currentConversationId && !route.params.id) {
      router.replace(`/chat/${chatStore.currentConversationId}`)
    }
  },
)

watch(
  () => [chatStore.messages.length, chatStore.streamContent],
  async () => {
    await nextTick()
    messagesContainer.value?.lastElementChild?.scrollIntoView({
      behavior: 'smooth',
    })
  },
)

// ── Send message ──

async function handleSend(content: string) {
  if (!chatStore.currentConversationId) {
    await chatStore.createConversation(content.slice(0, 30) + (content.length > 30 ? '...' : ''))
  }

  chatStore.addUserMessage(content)
  chatStore.startStreaming()

  startStream(
    '/api/v1/chat/stream',
    {
      conversation_id: chatStore.currentConversationId,
      message: content,
    },
    (msg) => {
      chatStore.handleStreamMsg(msg)
    },
    (err) => {
      console.error('SSE error:', err)
      toastStore.error('流式连接失败: ' + (err.message || '未知错误'))
      chatStore.isStreaming = false
    },
  )
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left: Chat main -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <!-- Messages Area -->
      <div
        ref="messagesContainer"
        class="flex-1 overflow-y-auto"
      >
        <!-- Empty state -->
        <div
          v-if="!chatStore.currentConversationId && !chatStore.isStreaming"
          class="flex h-full flex-col items-center justify-center px-4"
        >
          <div
            class="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-sky-400 shadow-lg mb-6"
          >
            <Sparkles :size="32" class="text-white" />
          </div>
          <h2 class="text-xl font-semibold text-slate-800 mb-2">
            MedRAG 医学文献助手
          </h2>
          <p class="max-w-md text-center text-sm text-slate-500 leading-relaxed">
            基于 RAG 技术的医学文献智能问答系统。点击左侧「发起新对话」开始提问，获取基于真实文献的精准回答。
          </p>
        </div>

        <!-- Messages -->
        <template v-for="msg in chatStore.messages" :key="msg.id">
          <MessageBubble
            :message="msg"
            @citation-click="handleCitationClick"
            @show-citation-list="showCitationList"
          />
        </template>

        <!-- Live streaming message -->
        <div v-if="chatStore.isStreaming">
          <MessageBubble
            :message="streamMessageWithRagSteps"
            :is-streaming="true"
            :stream-content="chatStore.revealedContent"
            @citation-click="handleCitationClick"
            @show-citation-list="showCitationList"
          />
        </div>

        <LoadingSpinner
          v-if="chatStore.messages.length === 0 && chatStore.isStreaming"
          text="正在思考..."
        />

      </div>

      <!-- Input -->
      <ChatInput :disabled="chatStore.isStreaming" @send="handleSend" />
    </div>

    <!-- Right: Citation panel -->
    <RightPanel
      v-if="rightPanelOpen"
      :citations="uniqueCitations"
      :active-citation="activeCitation"
      :pdf-url="pdfUrl"
      :pdf-loading="pdfLoading"
      :show-back-button="showBackButton"
      @close="closeRightPanel"
      @back-to-list="goBackToList"
      @select-citation="handlePanelSelectCitation"
    />
  </div>
</template>
