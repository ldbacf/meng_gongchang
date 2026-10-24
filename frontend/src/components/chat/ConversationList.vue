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
    <!-- 标题 -->
    <div
      v-if="!chatStore.conversationsLoading && sortedList.length"
      class="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[.4px] text-faint"
    >
      最近
    </div>

    <!-- 骨架 -->
    <div v-if="chatStore.conversationsLoading" class="space-y-1.5 px-2 py-2">
      <div v-for="i in 4" :key="'cs-' + i" class="flex items-center gap-2.5">
        <div class="skeleton h-3.5 w-3.5 rounded" />
        <div class="skeleton h-3 flex-1" :style="{ width: `${60 + i * 8}%` }" />
      </div>
    </div>

    <p
      v-if="!chatStore.conversationsLoading && sortedList.length === 0"
      class="px-3 py-6 text-center text-[12px] text-faint"
    >
      暂无历史对话
    </p>

    <!-- 会话项 -->
    <div
      v-for="conv in sortedList"
      :key="conv.id"
      class="group flex w-full cursor-pointer items-center gap-2.5 rounded-full px-2.5 py-2 text-left text-[13.5px] transition-colors"
      :class="
        chatStore.currentConversationId === conv.id
          ? 'bg-accent-soft text-accent-text font-medium'
          : 'text-ink-2 hover:bg-hover'
      "
      role="button"
      tabindex="0"
      @click="handleRowClick(conv)"
      @dblclick="handleRowDblClick(conv)"
      @keydown.enter="selectConv(conv.id)"
    >
      <MessageSquare
        :size="14"
        class="shrink-0"
        :class="chatStore.currentConversationId === conv.id ? 'text-accent' : 'text-faint'"
      />

      <!-- 重命名 -->
      <input
        v-if="editingId === conv.id"
        :id="`conv-edit-${conv.id}`"
        v-model="editTitle"
        class="min-w-0 flex-1 rounded border border-accent bg-canvas px-1.5 py-0.5 text-[13px] text-ink outline-none"
        maxlength="50"
        @blur="saveEdit"
        @keydown="handleEditKeydown"
        @click.stop
      />

      <span v-else class="min-w-0 flex-1 truncate">{{ conv.title }}</span>

      <!-- 删除确认 -->
      <template v-if="confirmDeleteId === conv.id">
        <button
          class="grid h-6 w-6 shrink-0 place-items-center rounded-full text-danger transition-colors hover:bg-danger-soft"
          title="确认删除"
          @click="(e: Event) => confirmDelete(conv.id, e)"
        >
          <Trash2 :size="13" />
        </button>
        <button
          class="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-hover"
          title="取消"
          @click="cancelDelete"
        >
          <span class="text-[11px]">✕</span>
        </button>
      </template>

      <!-- 行内操作 -->
      <template v-else-if="editingId !== conv.id">
        <button
          class="grid h-6 w-6 shrink-0 place-items-center rounded-full text-faint opacity-0 transition-all hover:bg-hover hover:text-accent group-hover:opacity-100"
          title="重命名"
          @click.stop="startEdit(conv)"
        >
          <Pencil :size="12" />
        </button>
        <button
          class="grid h-6 w-6 shrink-0 place-items-center rounded-full text-faint opacity-0 transition-all hover:bg-danger-soft hover:text-danger group-hover:opacity-100"
          title="删除"
          @click="(e: Event) => requestDelete(conv.id, e)"
        >
          <Trash2 :size="13" />
        </button>
      </template>
    </div>
  </div>
</template>
