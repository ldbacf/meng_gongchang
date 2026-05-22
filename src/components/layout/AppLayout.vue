<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { PanelLeftClose, PanelLeft } from 'lucide-vue-next'
import Sidebar from './Sidebar.vue'

const isCollapsed = ref(false)

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !isCollapsed.value) {
    isCollapsed.value = true
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div
    class="flex h-screen overflow-hidden bg-slate-50 transition-all duration-300"
  >
    <!-- Sidebar -->
    <div
      class="transition-all duration-300 ease-in-out"
      :class="isCollapsed ? 'w-0 overflow-hidden' : 'w-[280px]'"
    >
      <Sidebar :collapsed="isCollapsed" />
    </div>

    <!-- Main Content -->
    <div class="relative flex flex-1 flex-col overflow-hidden z-10">
      <!-- Overlay mask: click to close sidebar (mobile only; desktop passes clicks through) -->
      <div
        v-if="!isCollapsed"
        class="absolute inset-0 z-10 bg-black/20 backdrop-blur-sm transition-opacity duration-300 lg:pointer-events-none lg:bg-transparent lg:backdrop-blur-none"
        @click="toggleSidebar"
      />

      <!-- Top bar -->
      <header
        class="relative z-20 flex h-14 items-center gap-3 border-b bg-white/80 backdrop-blur-xl px-4"
      >
        <button
          class="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors"
          @click="toggleSidebar"
        >
          <PanelLeftClose v-if="!isCollapsed" :size="20" />
          <PanelLeft v-else :size="20" />
        </button>
        <span class="text-sm font-medium text-slate-600">
          {{ isCollapsed ? 'MedRAG' : '' }}
        </span>
      </header>

      <!-- Slot for page content -->
      <main class="flex-1 overflow-hidden">
        <slot />
      </main>
    </div>
  </div>
</template>
