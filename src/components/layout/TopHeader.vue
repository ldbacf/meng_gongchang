<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessageSquare, PanelLeft } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isAdmin = computed(() => authStore.isAdmin)

const isActive = (path: string) => route.path === path
</script>

<template>
  <!-- Mobile-friendly top header for collapsed mode -->
  <header class="flex h-14 items-center justify-between border-b bg-white/80 backdrop-blur-xl px-4 lg:hidden">
    <div class="flex items-center gap-3">
      <button
        class="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
      >
        <PanelLeft :size="20" />
      </button>
      <span class="font-semibold text-slate-800">MedRAG</span>
    </div>
  </header>
</template>
