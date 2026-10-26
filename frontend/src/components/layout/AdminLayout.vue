<script setup lang="ts">
/**
 * 后台管理外壳。
 *
 * 与聊天页是**两个独立的界面**：这里不出现会话侧栏，左侧换成后台自己的
 * 竖向导航（知识库管理 / 用户管理），顶部给你一条回对话的路。
 *
 * 路由上它是 `/admin` 的父记录，子页面通过 `<router-view />` 渲染。
 */
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Database, Users, ArrowLeft, LogOut, Sun, Moon } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useAuth } from '@/composables/useAuth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { logout } = useAuth()

// 后台没有聊天页那条顶栏，主题切换挪到侧栏底部，避免进来就切不回去
const isDark = ref(document.documentElement.classList.contains('dark'))

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('medrag_theme', isDark.value ? 'dark' : 'light')
}

const NAV = [
  { key: 'knowledge', label: '知识库管理', icon: Database, to: '/admin/knowledge' },
  { key: 'users', label: '用户管理', icon: Users, to: '/admin/users' },
]

/** 详情页 `/admin/knowledge/:kbId` 也要让「知识库管理」保持高亮 */
const activeKey = computed(() =>
  route.path.startsWith('/admin/knowledge') ? 'knowledge' : 'users',
)

function backToChat() {
  router.push('/chat')
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-canvas text-ink">
    <!-- 后台侧栏 -->
    <aside class="flex w-[232px] shrink-0 flex-col border-r border-line bg-surface">
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
          <div class="text-[11px] text-muted">后台管理</div>
        </div>
      </div>

      <!-- 返回对话 -->
      <div class="px-2">
        <button
          class="flex h-9 w-full items-center gap-2.5 rounded-full border border-line bg-surface-2 px-3.5 text-[13px] text-ink-2 transition-colors hover:bg-hover"
          @click="backToChat"
        >
          <ArrowLeft :size="14" class="shrink-0" />
          返回对话
        </button>
      </div>

      <!-- 导航：组间 mt-5 与上方拉开，组内 space-y-0.5 靠近 -->
      <nav class="mt-5 px-2">
        <div class="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-[.4px] text-faint">
          管理
        </div>
        <div class="space-y-0.5">
          <RouterLink
            v-for="item in NAV"
            :key="item.key"
            :to="item.to"
            class="flex h-9 items-center gap-2.5 rounded-full px-2.5 text-[13.5px] transition-colors"
            :class="
              activeKey === item.key
                ? 'bg-accent-soft font-medium text-accent-text'
                : 'text-ink-2 hover:bg-hover hover:text-ink'
            "
          >
            <component :is="item.icon" :size="14" class="shrink-0" />
            {{ item.label }}
          </RouterLink>
        </div>
      </nav>

      <div class="flex-1" />

      <!-- 当前账号 -->
      <div class="flex items-center gap-2.5 border-t border-line px-3 py-2">
        <div
          class="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] font-semibold text-white"
          style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
        >
          {{ (authStore.user?.username || 'U').slice(0, 1).toUpperCase() }}
        </div>
        <div class="min-w-0 flex-1 leading-tight">
          <div class="truncate text-[13px] font-medium">{{ authStore.user?.username }}</div>
          <div class="text-[11px] text-muted">管理员</div>
        </div>
        <button
          class="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-hover hover:text-ink"
          :title="isDark ? '切换到浅色' : '切换到深色'"
          @click="toggleTheme"
        >
          <Sun v-if="isDark" :size="15" />
          <Moon v-else :size="15" />
        </button>
        <button
          class="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-danger-soft hover:text-danger"
          title="退出登录"
          @click="logout"
        >
          <LogOut :size="15" />
        </button>
      </div>
    </aside>

    <!-- 内容区 -->
    <main class="flex-1 overflow-hidden">
      <RouterView />
    </main>
  </div>
</template>
