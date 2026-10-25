<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { PanelLeft, Sun, Moon, Share2 } from 'lucide-vue-next'
import Sidebar from './Sidebar.vue'

/**
 * `bare`：只渲染内容，不渲染侧栏/顶栏外壳。
 *
 * 给「后台管理」这类**自身已经是子页面**的场景用 —— 否则会套两层 AppLayout
 * （侧栏套侧栏、顶栏套顶栏）。
 */
withDefaults(defineProps<{ bare?: boolean }>(), { bare: false })

const isCollapsed = ref(false)
const isDark = ref(document.documentElement.classList.contains('dark'))

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value
}

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('medrag_theme', isDark.value ? 'dark' : 'light')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !isCollapsed.value) isCollapsed.value = true
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <!-- bare：外层已经有完整布局，这里只透传内容 -->
  <slot v-if="bare" />

  <div v-else class="flex h-screen overflow-hidden bg-canvas text-ink">
    <!-- Sidebar：宽度过渡，收起时整块移出 -->
    <div
      class="shrink-0 overflow-hidden transition-[width] duration-300 ease-[cubic-bezier(.2,.7,.3,1)]"
      :class="isCollapsed ? 'w-0' : 'w-[276px]'"
    >
      <Sidebar :collapsed="isCollapsed" />
    </div>

    <!-- 移动端遮罩 -->
    <div
      v-if="!isCollapsed"
      class="absolute inset-0 z-10 bg-black/25 lg:hidden"
      @click="toggleSidebar"
    />

    <div class="relative z-20 flex flex-1 flex-col overflow-hidden">
      <header class="flex h-[60px] shrink-0 items-center gap-2 px-3">
        <button
          class="grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
          title="切换侧栏"
          @click="toggleSidebar"
        >
          <PanelLeft :size="18" />
        </button>

        <div class="flex-1" />

        <button
          class="grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
          :title="isDark ? '切换到浅色' : '切换到深色'"
          @click="toggleTheme"
        >
          <Sun v-if="isDark" :size="17" />
          <Moon v-else :size="17" />
        </button>
        <button
          class="grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
          title="分享"
        >
          <Share2 :size="16" />
        </button>
      </header>

      <main class="flex-1 overflow-hidden">
        <slot />
      </main>
    </div>
  </div>
</template>
