<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import type { Citation } from '@/types'

import { useSSE } from '@/composables/useSSE'
import { useToastStore } from '@/stores/toast'
import { useAdminStore } from '@/stores/admin'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import EmptyState from './EmptyState.vue'
import RightPanel from './RightPanel.vue'
import { Library } from 'lucide-vue-next'

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
  // 流式期间也要能点引用：citations 走 store 的累积数组
  citations: chatStore.streamCitations,
}))

/**
 * 流式气泡只在「当前会话 === 正在生成的会话」时渲染。
 *
 * 这样中途切到别的对话再切回来，正在跑的回答还在；切到别处时那条气泡
 * 也不会串进别人的会话。
 */
const showStreaming = computed(
  () =>
    chatStore.isStreaming &&
    chatStore.streamingConversationId === chatStore.currentConversationId,
)

// ── Right panel state ──

const rightPanelOpen = ref(false)
const activeCitation = ref<Citation | null>(null)
const pdfUrl = ref<string | null>(null)
let _currentBlobUrl: string | null = null
const pdfLoading = ref(false)
const showBackButton = ref(false)

const uniqueCitations = computed(() => {
  // key 必须含消息 id：cite.id 是「该条回答内的序号」("1".."5")，跨消息会重复。
  // 只用 id 做 key 会让多轮会话里第 2/3 轮的引用被第 1 轮的同号引用顶掉。
  const map = new Map<string, Citation>()
  for (const msg of chatStore.messages) {
    for (const cite of msg.citations ?? []) {
      const key = `${msg.id}:${cite.id}`
      if (!map.has(key)) {
        map.set(key, cite)
      }
    }
  }
  return Array.from(map.values())
})

function _setPdfUrl(url: string | null) {
  if (_currentBlobUrl) {
    URL.revokeObjectURL(_currentBlobUrl)
    _currentBlobUrl = null
  }
  pdfUrl.value = url
}

/** pdf.js 走 Range 请求时的附加头（接口需 Bearer 鉴权）。 */
const pdfHeaders = computed<Record<string, string>>(() => {
  const token = localStorage.getItem('access_token')
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
})

async function loadPdfForCitation(citation: Citation) {
  activeCitation.value = citation
  rightPanelOpen.value = true
  _setPdfUrl(null)

  // 直接把接口 URL 交给 PdfViewer / pdf.js，由它按 Range 分片拉取。
  // 曾先 axios 拿整份 blob 再渲染：2MB 要等约 8s 才出第一页（链路约 250 KB/s）。
  if (citation.doc_id) {
    pdfLoading.value = false
    _setPdfUrl(`/api/v1/documents/${citation.doc_id}/pdf/stream`)
    return
  }

  pdfLoading.value = true
  _setPdfUrl(citation.pdfUrl ?? null)
  pdfLoading.value = false
}

async function handleCitationClick(citation: Citation) {
  showBackButton.value = false
  await loadPdfForCitation(citation)
}

function showCitationList() {
  showBackButton.value = true
  activeCitation.value = null
  _setPdfUrl(null)
  rightPanelOpen.value = true
}

function closeRightPanel() {
  rightPanelOpen.value = false
  activeCitation.value = null
  _setPdfUrl(null)
}

function goBackToList() {
  activeCitation.value = null
  _setPdfUrl(null)
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
    chatStore.streamingConversationId = null
    chatStore.streamContent = ''
    chatStore.streamCitations = []
  }
}

watch(
  () => route.params.id,
  async (newId) => {
    // 不再 abort：切换到别的会话时让 SSE 继续跑，切回来还能看到进行中的回答
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
    // 只有当用户还停在这个会话里时才补写 URL；切到别处后不要把人拽回来
    if (
      !streaming &&
      chatStore.currentConversationId &&
      !route.params.id &&
      chatStore.streamingConversationId === null
    ) {
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
  <div class="relative flex h-full overflow-hidden">
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- 消息区 -->
      <div ref="messagesContainer" class="flex-1 overflow-y-auto">
        <!-- 空状态 -->
        <EmptyState
          v-if="!chatStore.currentConversationId && !showStreaming && !messagesLoading"
          @ask="handleSend"
        />

        <!-- 会话内容 -->
        <div v-else class="mx-auto w-full max-w-chat px-6 pb-8 pt-1">
          <!-- 骨架 -->
          <div v-if="messagesLoading" class="space-y-7 py-4">
            <div v-for="i in 3" :key="'sk-' + i" class="flex gap-3.5">
              <div class="skeleton h-[26px] w-[26px] shrink-0 rounded-full" />
              <div class="flex-1 space-y-2.5">
                <div class="skeleton h-3 w-2/5" />
                <div class="skeleton h-3 w-full" />
                <div class="skeleton h-3 w-4/5" />
              </div>
            </div>
          </div>

          <template v-else>
            <TransitionGroup name="msg">
              <template v-for="msg in chatStore.messages" :key="msg.id">
                <MessageBubble
                  :message="msg"
                  @citation-click="handleCitationClick"
                  @show-citation-list="showCitationList"
                />
              </template>
            </TransitionGroup>

            <!-- 正在流式输出的消息（只在它所属的会话里显示） -->
            <div v-if="showStreaming">
              <MessageBubble
                :message="streamMessageWithRagSteps"
                :is-streaming="true"
                :stream-content="chatStore.revealedContent"
                @citation-click="handleCitationClick"
                @show-citation-list="showCitationList"
              />
            </div>
          </template>
        </div>
      </div>

      <!-- 当前知识库 -->
      <div
        v-if="adminStore.activeKb"
        class="flex items-center justify-center gap-1.5 pb-1 text-[11px] text-faint"
      >
        <Library :size="11" />
        当前知识库 · <span class="font-medium text-muted">{{ adminStore.activeKb.name }}</span>
      </div>

      <ChatInput
        :streaming="chatStore.isStreaming"
        @send="handleSend"
        @stop="abortStreaming"
      />
    </div>

    <!-- 右侧文献面板（覆盖式滑出） -->
    <Transition name="panel">
      <RightPanel
        v-if="rightPanelOpen"
        :citations="uniqueCitations"
        :active-citation="activeCitation"
        :pdf-url="pdfUrl"
        :pdf-loading="pdfLoading"
        :show-back-button="showBackButton"
        :pdf-headers="pdfHeaders"
        @close="closeRightPanel"
        @back-to-list="goBackToList"
        @select-citation="handlePanelSelectCitation"
      />
    </Transition>
  </div>
</template>
