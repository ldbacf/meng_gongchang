<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { PanelLeft, Sun, Moon, Share2 } from 'lucide-vue-next'
import Sidebar from './Sidebar.vue'

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
  <div class="flex h-screen overflow-hidden bg-canvas text-ink">
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

        <button
          class="inline-flex items-center gap-2 rounded-full border border-line px-3 py-[7px] text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface hover:border-line-strong"
        >
          <span class="h-[7px] w-[7px] rounded-full bg-[linear-gradient(100deg,var(--grad-1),var(--grad-2),var(--grad-3))]" />
          MedRAG 2.0
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m6 9 6 6 6-6" /></svg>
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
