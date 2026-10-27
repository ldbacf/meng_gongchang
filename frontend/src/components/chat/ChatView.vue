<script setup lang="ts">
/**
 * 聊天主视图。
 *
 * 只负责**串联**：把 store、SSE、滚动跟随、引用面板接起来，并把消息列渲染出来。
 * 具体逻辑分别在：
 *   - `useStickToBottom` — 滚动跟随 / 不打扰 / 主动归位
 *   - `useCitationPanel` — 右侧文献面板状态、引用去重、PDF 地址
 *   - `stores/chat`       — 流式内容累积、逐字 reveal、消息落库同步
 *
 * 之前这些全挤在这一个文件里（418 行），改滚动要读一遍面板代码才敢动。
 */
import { ref, watch, onMounted, onUnmounted, computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import type { Citation, Message } from '@/types'

import { useSSE } from '@/composables/useSSE'
import { useToastStore } from '@/stores/toast'
import { useAdminStore } from '@/stores/admin'
import { useStickToBottom } from '@/composables/useStickToBottom'
import { useCitationPanel } from '@/composables/useCitationPanel'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import EmptyState from './EmptyState.vue'
import { Library } from 'lucide-vue-next'

/**
 * 右侧文献面板异步加载。
 *
 * `RightPanel → PdfViewer → pdfjs-dist + pdf_viewer.css` 合计约 580 KB JS + 278 KB CSS。
 * 原来静态 import，即使 `v-if` 从没打开过，这些也会全部打进 ChatView 主 chunk，
 * 用户一进聊天页就要下载。改成异步后只在首次点开引用时才拉。
 */
const RightPanel = defineAsyncComponent(() => import('./RightPanel.vue'))

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const toastStore = useToastStore()
const adminStore = useAdminStore()
const { startStream, abort: abortSSE } = useSSE()

const messagesContainer = ref<HTMLElement | null>(null)
const messagesLoading = ref(false)

// ── 滚动跟随 ──

// watch 的触发源：消息条数 + 流式内容长度。只放这两个，
// 不要把整个 messages 数组塞进去（引用变化会连带触发滚动）。
const {
  stickToBottom,
  onScroll: onMessagesScroll,
  forceBottom,
} = useStickToBottom(messagesContainer, () => [
  chatStore.messages.length,
  chatStore.streamContent,
])

// ── 引用面板 ──

const {
  open: rightPanelOpen,
  activeCitation,
  pdfUrl,
  pdfLoading,
  highlightBoxes,
  locateMessage,
  showBackButton,
  uniqueCitations,
  pdfHeaders,
  evidence,
  evidenceLoading,
  view: rightPanelView,
  openCitation,
  openList,
  backToList,
  showPdf,
  showEvidence,
  close: closeRightPanel,
} = useCitationPanel(computed(() => chatStore.messages))

function handleCitationClick(citation: Citation) {
  openCitation(citation)
}

function showCitationList() {
  openList()
}

function handlePanelSelectCitation(citation: Citation) {
  // 从列表点进详情：保留「返回列表」
  openCitation(citation, true)
}

// ── 流式气泡 ──

const streamMessage: Message = {
  id: 'streaming',
  role: 'ai',
  content: '',
  timestamp: Date.now(),
}

const streamMessageWithRagSteps = computed<Message>(() => ({
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
    // 不 abort：切换到别的会话时让 SSE 继续跑，切回来还能看到进行中的回答
    if (newId && typeof newId === 'string') {
      if (chatStore.currentConversationId !== newId) {
        messagesLoading.value = true
        await chatStore.selectConversation(newId)
        messagesLoading.value = false
        // 切会话：直接落到底部（新会话默认看最新一条），不要平滑动画
        await forceBottom(false)
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

// ── Send message ──

/**
 * 发起一次流式请求。
 *
 * `regenerateMessageId` 非空表示「重新生成」：复用 `content`（原提问）重新回答，
 * 后端不会新建用户消息，并在新回答落库时删掉被替换的那条。
 */
function startQuestion(content: string, opts: { regenerateMessageId?: string } = {}) {
  chatStore.startStreaming()

  const body: Record<string, unknown> = {
    conversation_id: chatStore.currentConversationId,
    message: content,
    kb_id: adminStore.activeKbId,
  }
  if (opts.regenerateMessageId) body.regenerate_message_id = opts.regenerateMessageId

  startStream(
    '/api/v1/chat/stream',
    body,
    (msg) => {
      chatStore.handleStreamMsg(msg)
    },
    (err) => {
      console.error('SSE error:', err)
      toastStore.error('流式连接失败: ' + (err.message || '未知错误'))
      chatStore.isStreaming = false
      // 重新生成失败：本地已移除了旧回答，从服务端拉回真实状态
      if (opts.regenerateMessageId && chatStore.currentConversationId) {
        chatStore.selectConversation(chatStore.currentConversationId)
      }
    },
  )
}

async function handleSend(content: string) {
  if (!chatStore.currentConversationId) {
    await chatStore.createConversation(content.slice(0, 30) + (content.length > 30 ? '...' : ''))
  }

  chatStore.addUserMessage(content)
  // 主动发消息：无论之前是否往上翻，都跟到底部
  stickToBottom.value = true
  startQuestion(content)
}

/** 最近一条 AI 回答的 id —— 只有它能「重新生成」 */
const lastAiMessageId = computed(() => {
  for (let i = chatStore.messages.length - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'ai') return chatStore.messages[i].id
  }
  return null
})

/**
 * 重新生成：找到这条 AI 回答**前面最近的一条用户提问**，用它重发。
 *
 * - 本地先移除旧回答（视觉上立即让位给流式气泡）
 * - 服务端在新回答落库的同一事务里删除旧回答；失败则保留，前端会回拉一次消息列表
 */
async function handleRegenerate(message: { id: string }) {
  if (chatStore.isStreaming) return

  const idx = chatStore.messages.findIndex((m) => m.id === message.id)
  if (idx < 0) return

  let question = ''
  for (let i = idx - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'user') {
      question = chatStore.messages[i].content
      break
    }
  }
  if (!question) {
    toastStore.error('找不到对应的提问，无法重新生成')
    return
  }

  chatStore.removeMessage(message.id)
  stickToBottom.value = true
  startQuestion(question, { regenerateMessageId: message.id })
}
</script>

<template>
  <div class="relative flex h-full overflow-hidden">
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- 消息区 -->
      <div
        ref="messagesContainer"
        class="flex-1 overflow-y-auto"
        @scroll.passive="onMessagesScroll"
      >
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
                  :can-regenerate="!chatStore.isStreaming && msg.id === lastAiMessageId"
                  @citation-click="handleCitationClick"
                  @show-citation-list="showCitationList"
                  @regenerate="handleRegenerate(msg)"
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

      <ChatInput :streaming="chatStore.isStreaming" @send="handleSend" @stop="abortStreaming" />
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
        :highlight-boxes="highlightBoxes"
        :locate-message="locateMessage"
        :evidence="evidence"
        :evidence-loading="evidenceLoading"
        :view="rightPanelView"
        @close="closeRightPanel"
        @back-to-list="backToList"
        @select-citation="handlePanelSelectCitation"
        @open-pdf="showPdf"
        @show-evidence="showEvidence"
      />
    </Transition>
  </div>
</template>
