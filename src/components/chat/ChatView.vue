<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'
import type { StreamChunk, Citation } from '@/types'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { Sparkles } from 'lucide-vue-next'

const route = useRoute()
const chatStore = useChatStore()
const { isStreaming: sseStreaming, startStream } = useSSE()

const messagesContainer = ref<HTMLElement | null>(null)

onMounted(async () => {
  await chatStore.fetchConversations()

  const convId = route.params.id as string | undefined
  if (convId) {
    chatStore.selectConversation(convId)
  } else {
    await chatStore.createConversation()
  }
})

watch(
  () => route.params.id,
  async (newId) => {
    if (newId && typeof newId === 'string') {
      chatStore.selectConversation(newId)
    }
  },
)

// Auto-scroll to bottom when messages change
watch(
  () => [chatStore.messages.length, chatStore.streamContent],
  async () => {
    await nextTick()
    messagesContainer.value?.lastElementChild?.scrollIntoView({
      behavior: 'smooth',
    })
  },
)

async function handleSend(content: string) {
  if (!chatStore.currentConversationId) {
    await chatStore.createConversation()
  }

  chatStore.addUserMessage(content)
  chatStore.startStreaming()

  await startStream(
    '/api/chat/stream',
    {
      conversationId: chatStore.currentConversationId,
      message: content,
    },
    (chunk: StreamChunk) => {
      switch (chunk.type) {
        case 'text':
          chatStore.appendStreamContent(chunk.data as string)
          break
        case 'citation':
          chatStore.addStreamCitation(chunk.data as Citation)
          break
        case 'done':
          chatStore.finishStreaming()
          break
        case 'error':
          chatStore.finishStreaming()
          break
      }
    },
    () => {
      // On error, finalize with accumulated content
      chatStore.finishStreaming()
    },
  )
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Messages Area -->
    <div
      ref="messagesContainer"
      class="flex-1 overflow-y-auto"
    >
      <!-- Empty state -->
      <div
        v-if="chatStore.messages.length === 0 && !chatStore.isStreaming"
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
          基于 RAG 技术的医学文献智能问答系统。输入您的问题，获取基于真实文献的精准回答。
        </p>
      </div>

      <!-- Messages -->
      <template v-for="msg in chatStore.messages" :key="msg.id">
        <MessageBubble :message="msg" />
      </template>

      <!-- Live streaming message -->
      <div v-if="chatStore.isStreaming">
        <MessageBubble
          :message="{
            id: 'streaming',
            role: 'ai',
            content: '',
            timestamp: Date.now(),
          }"
          :is-streaming="true"
          :stream-content="chatStore.streamContent"
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
</template>
