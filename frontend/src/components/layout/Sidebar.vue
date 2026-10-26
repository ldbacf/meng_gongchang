<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Settings, LogOut, ChevronUp } from 'lucide-vue-next'
import ConversationList from '@/components/chat/ConversationList.vue'
import { useAuthStore } from '@/stores/auth'
import { useAuth } from '@/composables/useAuth'

defineProps<{ collapsed: boolean }>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { logout } = useAuth()

const isAdmin = computed(() => authStore.isAdmin)
const isCreating = ref(false)

// ── 用户菜单 ────────────────────────────────────────────────
//
// 原来「知识库管理 / 用户管理」是侧栏里两个常驻入口，占空间且只对管理员有意义。
// 现在收进头像菜单：设置（→ 后台管理页）/ 退出登录。
const menuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function closeMenu() {
  menuOpen.value = false
}

/**
 * 设置 = 后台管理（独立界面，左侧有自己的管理导航）；普通用户没有后台，菜单里就不显示该项。
 */
function goSettings() {
  closeMenu()
  if (isAdmin.value) router.push('/admin')
}

async function doLogout() {
  closeMenu()
  await logout()
}

function onDocClick(e: MouseEvent) {
  if (!menuOpen.value) return
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) closeMenu()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') closeMenu()
  // Ctrl+, 打开设置（与常见桌面应用一致）
  if ((e.ctrlKey || e.metaKey) && e.key === ',') {
    e.preventDefault()
    if (isAdmin.value) router.push('/admin')
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
})

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
    <div class="flex items-center gap-2.5 px-4 pb-4 pt-4">
      <div
        class="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[13px] font-bold text-white shadow-[0_2px_8px_rgba(66,133,244,.35)]"
        style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
      >
        M
      </div>
      <div class="min-w-0 leading-tight">
        <div class="text-[15px] font-semibold tracking-[.2px]">MedRAG</div>
        <div class="text-[11px] text-muted">医学文献智能问答</div>
      </div>
    </div>

    <!-- 新对话：与下方列表同宽同边距，避免视觉错位 -->
    <div class="px-2">
      <button
        :disabled="isCreating"
        class="flex h-10 w-full items-center gap-2.5 rounded-full border border-line bg-surface-2 px-3.5 text-[13.5px] font-medium text-ink-2 shadow-sm transition-all hover:bg-hover hover:shadow active:scale-[.99] disabled:opacity-50"
        @click="startNewChat"
      >
        <Plus :size="15" class="shrink-0" />
        新对话
      </button>
    </div>

    <!-- 会话列表 -->
    <div class="flex-1 overflow-y-auto px-2 py-4">
      <ConversationList />
    </div>

    <!-- 用户区：点击头像弹出菜单 -->
    <div ref="menuRef" class="relative border-t border-line px-2 py-2">
      <!-- 弹出菜单 -->
      <Transition name="menu">
        <div
          v-if="menuOpen"
          class="absolute bottom-[calc(100%-2px)] left-2 right-2 z-30 overflow-hidden rounded-xl border border-line bg-surface-2 p-1 shadow-lg"
        >
          <button
            v-if="isAdmin"
            class="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] text-ink-2 transition-colors hover:bg-hover hover:text-ink"
            @click="goSettings"
          >
            <Settings :size="14" class="shrink-0 text-muted" />
            设置
            <span class="ml-auto font-mono text-[10.5px] text-faint">Ctrl + ,</span>
          </button>
          <button
            class="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] text-danger transition-colors hover:bg-danger-soft"
            @click="doLogout"
          >
            <LogOut :size="14" class="shrink-0" />
            退出登录
          </button>
        </div>
      </Transition>

      <!-- 头像行（整块可点）：与新对话、会话行同高 -->
      <button
        class="flex h-11 w-full items-center gap-2.5 rounded-full px-2 transition-colors hover:bg-hover"
        :title="isAdmin ? '设置 · 退出登录' : '退出登录'"
        @click.stop="toggleMenu"
      >
        <div
          class="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] font-semibold text-white"
          style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
        >
          {{ (authStore.user?.username || 'U').slice(0, 1).toUpperCase() }}
        </div>
        <div class="min-w-0 flex-1 text-left leading-tight">
          <div class="truncate text-[13px] font-medium">{{ authStore.user?.username }}</div>
          <div class="text-[11px] text-muted">{{ isAdmin ? '管理员' : '用户' }}</div>
        </div>
        <ChevronUp
          :size="14"
          class="shrink-0 text-faint transition-transform"
          :class="{ 'rotate-180': menuOpen }"
        />
      </button>
    </div>
  </aside>
</template>

<style scoped>
.menu-enter-active,
.menu-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s cubic-bezier(0.2, 0.7, 0.3, 1);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}
</style>
