<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  MessageSquarePlus,
  MessageSquare,
  Database,
  Users,
  LogOut,
  ChevronLeft,
} from 'lucide-vue-next'
import AppLogo from '@/components/common/AppLogo.vue'
import ConversationList from '@/components/chat/ConversationList.vue'
import { useAuthStore } from '@/stores/auth'
import { useAuth } from '@/composables/useAuth'

defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { logout } = useAuth()

const isAdmin = computed(() => authStore.isAdmin)
const isActive = (path: string) => route.path === path

function navigate(path: string) {
  router.push(path)
}
</script>

<template>
  <aside
    class="flex h-full flex-col border-r bg-white/60 backdrop-blur-xl"
  >
    <!-- Logo Area -->
    <div class="flex items-center justify-between px-2 pt-2">
      <AppLogo :collapsed="collapsed" />
      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
        @click="emit('toggle')"
      >
        <ChevronLeft :size="18" />
      </button>
    </div>

    <!-- New Chat Button -->
    <div class="px-3 pt-4 pb-2">
      <button
        class="flex w-full items-center gap-2.5 rounded-xl border-2 border-dashed border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-600 hover:border-primary-400 hover:bg-primary-50/50 hover:text-primary-700 transition-all duration-200"
        @click="navigate('/chat')"
      >
        <MessageSquarePlus :size="18" />
        <span v-if="!collapsed">发起新对话</span>
      </button>
    </div>

    <!-- Conversation History -->
    <div class="flex-1 overflow-y-auto px-2">
      <ConversationList v-if="!collapsed" />
    </div>

    <!-- Admin Section -->
    <div
      v-if="isAdmin && !collapsed"
      class="border-t px-3 py-3 space-y-1"
    >
      <p class="px-2 text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
        管理后台
      </p>
      <button
        class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
        :class="
          isActive('/admin/knowledge')
            ? 'bg-primary-50 text-primary-700'
            : 'text-slate-600 hover:bg-slate-100'
        "
        @click="navigate('/admin/knowledge')"
      >
        <Database :size="18" />
        知识库管理
      </button>
      <button
        class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
        :class="
          isActive('/admin/users')
            ? 'bg-primary-50 text-primary-700'
            : 'text-slate-600 hover:bg-slate-100'
        "
        @click="navigate('/admin/users')"
      >
        <Users :size="18" />
        用户管理
      </button>
    </div>

    <!-- User Info & Logout -->
    <div class="border-t px-3 py-3">
      <div v-if="!collapsed" class="flex items-center justify-between">
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-slate-700">
            {{ authStore.user?.username }}
          </p>
          <p class="text-xs text-slate-400">
            {{ isAdmin ? '管理员' : '用户' }}
          </p>
        </div>
        <button
          class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500 transition-colors"
          @click="logout"
        >
          <LogOut :size="16" />
        </button>
      </div>
    </div>
  </aside>
</template>
