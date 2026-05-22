<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import { useRouter } from 'vue-router'
import { MessageSquare, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'

const chatStore = useChatStore()
const router = useRouter()

const sortedList = computed(() => chatStore.sortedConversations)

function selectConv(id: string) {
  chatStore.selectConversation(id)
  router.push(`/chat/${id}`)
}

async function deleteConv(id: string, event: Event) {
  event.stopPropagation()
  const isCurrent = chatStore.currentConversationId === id
  await chatStore.deleteConversation(id)
  if (isCurrent) {
    router.push('/chat')
  }
}
</script>

<template>
  <div class="space-y-0.5">
    <p
      v-if="sortedList.length === 0"
      class="px-2 py-4 text-center text-xs text-slate-400"
    >
      暂无历史对话
    </p>
    <div
      v-for="conv in sortedList"
      :key="conv.id"
      class="group flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-slate-100"
      :class="
        chatStore.currentConversationId === conv.id
          ? 'bg-slate-100 text-slate-900'
          : 'text-slate-600'
      "
      role="button"
      tabindex="0"
      @click="selectConv(conv.id)"
      @keydown.enter="selectConv(conv.id)"
    >
      <MessageSquare :size="16" class="shrink-0 text-slate-400" />
      <span class="flex-1 truncate">{{ conv.title }}</span>
      <button
        class="flex h-6 w-6 shrink-0 items-center justify-center rounded opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-all"
        @click="(e) => deleteConv(conv.id, e)"
      >
        <Trash2 :size="14" />
      </button>
    </div>
  </div>
</template>
