<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, MessageSquare, Database, Users, LogOut, Trash2, Pencil } from 'lucide-vue-next'
import ConversationList from '@/components/chat/ConversationList.vue'
import { useAuthStore } from '@/stores/auth'
import { useAuth } from '@/composables/useAuth'
import { useChatStore } from '@/stores/chat'

defineProps<{ collapsed: boolean }>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const chatStore = useChatStore()
const { logout } = useAuth()

const isAdmin = computed(() => authStore.isAdmin)
const isActive = (path: string) => route.path === path
const isCreating = ref(false)

function navigate(path: string) {
  router.push(path)
}

async function startNewChat() {
  if (isCreating.value) return
  isCreating.value = true
  try {
    router.push('/chat')
  } finally {
    isCreating.value = false
  }
}
</script>

<template>
  <aside class="flex h-full w-[276px] flex-col bg-surface">
    <!-- 品牌 -->
    <div class="flex items-center gap-2.5 px-4 pb-3 pt-4">
      <div
        class="grid h-7 w-7 place-items-center rounded-lg text-[13px] font-bold text-white shadow-[0_2px_8px_rgba(66,133,244,.35)]"
        style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
      >
        M
      </div>
      <div class="leading-tight">
        <div class="text-[15px] font-semibold tracking-[.2px]">MedRAG</div>
        <div class="text-[11px] text-muted">医学文献智能问答</div>
      </div>
    </div>

    <!-- 新对话 -->
    <div class="px-3 pb-1">
      <button
        :disabled="isCreating"
        class="flex w-full items-center gap-2.5 rounded-full border border-line bg-surface-2 px-3.5 py-2.5 text-[13.5px] font-medium text-ink-2 shadow-sm transition-all hover:bg-hover hover:shadow active:scale-[.99] disabled:opacity-50"
        @click="startNewChat"
      >
        <Plus :size="16" />
        新对话
      </button>
    </div>

    <!-- 会话列表 -->
    <div class="flex-1 overflow-y-auto px-2 py-2">
      <ConversationList />
    </div>

    <!-- 管理入口 -->
    <div v-if="isAdmin" class="px-2 pb-1">
      <div class="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[.4px] text-faint">
        管理后台
      </div>
      <button
        class="flex w-full items-center gap-2.5 rounded-full px-2.5 py-2 text-[13.5px] transition-colors"
        :class="isActive('/admin/knowledge') ? 'bg-accent-soft text-accent-text font-medium' : 'text-ink-2 hover:bg-hover'"
        @click="navigate('/admin/knowledge')"
      >
        <Database :size="15" />
        知识库管理
      </button>
      <button
        class="flex w-full items-center gap-2.5 rounded-full px-2.5 py-2 text-[13.5px] transition-colors"
        :class="isActive('/admin/users') ? 'bg-accent-soft text-accent-text font-medium' : 'text-ink-2 hover:bg-hover'"
        @click="navigate('/admin/users')"
      >
        <Users :size="15" />
        用户管理
      </button>
    </div>

    <!-- 用户 -->
    <div class="border-t border-line px-3 py-3">
      <div class="flex items-center gap-2.5">
        <div
          class="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] font-semibold text-white"
          style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
        >
          {{ (authStore.user?.username || 'U').slice(0, 1).toUpperCase() }}
        </div>
        <div class="min-w-0 flex-1 leading-tight">
          <div class="truncate text-[13px] font-medium">{{ authStore.user?.username }}</div>
          <div class="text-[11px] text-muted">{{ isAdmin ? '管理员' : '用户' }}</div>
        </div>
        <button
          class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-danger-soft hover:text-danger"
          title="退出登录"
          @click="logout"
        >
          <LogOut :size="15" />
        </button>
      </div>
    </div>
  </aside>
</template>
