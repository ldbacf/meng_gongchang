<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import { useRouter } from 'vue-router'
import { MessageSquare, Trash2, Pencil } from 'lucide-vue-next'
import { computed, ref, nextTick } from 'vue'
import type { Conversation } from '@/types'

const chatStore = useChatStore()
const router = useRouter()

const sortedList = computed(() => chatStore.sortedConversations)

// ── Inline rename ──

const editingId = ref<string | null>(null)
const editTitle = ref('')
let clickTimer: ReturnType<typeof setTimeout> | null = null

function handleRowClick(conv: Conversation) {
  if (editingId.value) return
  clickTimer = setTimeout(() => {
    clickTimer = null
    selectConv(conv.id)
  }, 250)
}

function handleRowDblClick(conv: Conversation) {
  if (clickTimer) {
    clearTimeout(clickTimer)
    clickTimer = null
  }
  startEdit(conv)
}

function selectConv(id: string) {
  chatStore.selectConversation(id)
  router.push(`/chat/${id}`)
}

const confirmDeleteId = ref<string | null>(null)

function requestDelete(id: string, event: Event) {
  event.stopPropagation()
  confirmDeleteId.value = id
}

function cancelDelete(event: Event) {
  event.stopPropagation()
  confirmDeleteId.value = null
}

async function confirmDelete(id: string, event: Event) {
  event.stopPropagation()
  confirmDeleteId.value = null
  const isCurrent = chatStore.currentConversationId === id
  await chatStore.deleteConversation(id)
  if (isCurrent) {
    router.push('/chat')
  }
}

function startEdit(conv: Conversation) {
  editingId.value = conv.id
  editTitle.value = conv.title
  nextTick(() => {
    const input = document.getElementById(`conv-edit-${conv.id}`) as HTMLInputElement
    input?.focus()
    input?.select()
  })
}

async function saveEdit() {
  const id = editingId.value
  const title = editTitle.value.trim()
  if (!id) return
  if (!title) {
    cancelEdit()
    return
  }
  await chatStore.renameConversation(id, title)
  editingId.value = null
  editTitle.value = ''
}

function cancelEdit() {
  editingId.value = null
  editTitle.value = ''
}

function handleEditKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    saveEdit()
  } else if (e.key === 'Escape') {
    cancelEdit()
  }
}
</script>

<template>
  <div class="space-y-0.5">
    <!-- Skeleton -->
    <div v-if="chatStore.conversationsLoading" class="space-y-1 px-3 py-2">
      <div v-for="i in 4" :key="'cs-' + i" class="flex items-center gap-2.5 py-1.5">
        <div class="h-4 w-4 shrink-0 rounded bg-slate-200 animate-pulse" />
        <div class="h-3 flex-1 rounded bg-slate-200 animate-pulse" :style="{ width: `${60 + i * 10}%` }" />
      </div>
    </div>
    <p
      v-if="!chatStore.conversationsLoading && sortedList.length === 0"
      class="px-2 py-4 text-center text-xs text-slate-400"
    >
      暂无历史对话
    </p>
    <div
      v-for="conv in sortedList"
      :key="conv.id"
      class="group flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:outline-none"
      :class="
        chatStore.currentConversationId === conv.id
          ? 'bg-slate-100 text-slate-900'
          : 'text-slate-600'
      "
      role="button"
      tabindex="0"
      @click="handleRowClick(conv)"
      @dblclick="handleRowDblClick(conv)"
      @keydown.enter="selectConv(conv.id)"
    >
      <MessageSquare :size="16" class="shrink-0 text-slate-400" />

      <!-- Edit mode -->
      <input
        v-if="editingId === conv.id"
        :id="`conv-edit-${conv.id}`"
        v-model="editTitle"
        class="flex-1 rounded border border-primary-300 bg-white px-1.5 py-0.5 text-sm text-slate-700 outline-none ring-1 ring-primary-300"
        maxlength="50"
        @blur="saveEdit"
        @keydown="handleEditKeydown"
        @click.stop
      />

      <!-- Normal display -->
      <span
        v-else
        class="flex-1 truncate"
      >{{ conv.title }}</span>

      <!-- Delete confirmation -->
      <template v-if="confirmDeleteId === conv.id">
        <span class="shrink-0 text-[11px] text-red-500">确认删除？</span>
        <button
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded text-red-500 hover:bg-red-50 transition-all"
          @click="(e: Event) => confirmDelete(conv.id, e)"
        >
          <Trash2 :size="14" />
        </button>
        <button
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 transition-all"
          @click="cancelDelete"
        >
          <span class="text-xs">✕</span>
        </button>
      </template>

      <!-- Normal actions -->
      <template v-else-if="editingId !== conv.id && confirmDeleteId !== conv.id">
        <button
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded opacity-0 group-hover:opacity-100 text-slate-400 hover:text-primary-500 transition-all"
          @click.stop="startEdit(conv)"
        >
          <Pencil :size="13" />
        </button>
        <button
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-all"
          @click="(e: Event) => requestDelete(conv.id, e)"
        >
          <Trash2 :size="14" />
        </button>
      </template>
    </div>
  </div>
</template>
