<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import type { Citation } from '@/types'
import { fetchDocumentPdfStreamUrl } from '@/api/document'
import { useSSE } from '@/composables/useSSE'
import { useToastStore } from '@/stores/toast'
import { useAdminStore } from '@/stores/admin'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import RightPanel from './RightPanel.vue'
import { Sparkles, Library } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const toastStore = useToastStore()
const adminStore = useAdminStore()
const { startStream, abort: abortSSE } = useSSE()

const messagesContainer = ref<HTMLElement | null>(null)
const messagesLoading = ref(false)

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
      pdfUrl.value = fetchDocumentPdfStreamUrl(citation.doc_id)
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

  await adminStore.fetchKnowledgeBases()
  if (!adminStore.activeKbId) {
    const defaultKb = adminStore.knowledgeBases.find((k) => k.slug === 'zhong_guo_quan_ke')
    if (defaultKb) adminStore.setActiveKb(defaultKb.id)
  }

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
        messagesLoading.value = true
        await chatStore.selectConversation(newId)
        messagesLoading.value = false
        await nextTick()
        messagesContainer.value?.lastElementChild?.scrollIntoView()
      }
    } else {
      chatStore.currentConversationId = null
      chatStore.messages = []
      messagesLoading.value = false
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
      kb_id: adminStore.activeKbId,
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
            class="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-sky-400 shadow-lg mb-6 animate-float"
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

        <!-- Skeleton loading -->
        <div v-if="messagesLoading" class="flex flex-col gap-3 px-4 py-4">
          <div v-for="i in 3" :key="'sk-' + i" class="flex gap-3 animate-pulse">
            <div class="h-8 w-8 shrink-0 rounded-full bg-slate-200" />
            <div class="flex-1 space-y-2">
              <div class="h-3 w-32 rounded bg-slate-200" />
              <div class="h-3 w-full rounded bg-slate-100" />
              <div class="h-3 w-3/4 rounded bg-slate-100" />
            </div>
          </div>
        </div>

        <!-- Messages -->
        <TransitionGroup name="msg">
          <template v-for="msg in chatStore.messages" :key="msg.id">
            <MessageBubble
              :message="msg"
              @citation-click="handleCitationClick"
              @show-citation-list="showCitationList"
            />
          </template>
        </TransitionGroup>

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
      <!-- Active KB indicator -->
      <div v-if="adminStore.activeKb" class="flex items-center justify-center border-t bg-white/50 px-4 py-1.5">
        <div class="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Library :size="12" class="text-primary-400" />
          <span>当前知识库：</span>
          <span class="font-medium text-slate-600">{{ adminStore.activeKb.name }}</span>
          <span class="text-slate-300">—</span>
          <span>在知识库管理中切换</span>
        </div>
      </div>
      <ChatInput :disabled="chatStore.isStreaming" @send="handleSend" />
    </div>

    <!-- Right: Citation panel -->
    <Transition name="panel">
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
    </Transition>
  </div>
</template>


