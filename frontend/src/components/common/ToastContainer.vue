<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-vue-next'

const toastStore = useToastStore()

function iconBg(type: string) {
  switch (type) {
    case 'success': return 'text-emerald-500 bg-emerald-50 border-emerald-200'
    case 'error': return 'text-red-500 bg-red-50 border-red-200'
    default: return 'text-blue-500 bg-blue-50 border-blue-200'
  }
}
</script>

<template>
  <div class="fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
    <TransitionGroup name="toast">
      <div
        v-for="t in toastStore.toasts"
        :key="t.id"
        class="flex items-center gap-2.5 rounded-lg border px-4 py-2.5 shadow-lg backdrop-blur-sm text-sm min-w-[280px] max-w-[400px]"
        :class="iconBg(t.type)"
      >
        <CheckCircle v-if="t.type === 'success'" :size="16" />
        <AlertCircle v-else-if="t.type === 'error'" :size="16" />
        <Info v-else :size="16" />
        <span class="flex-1 text-slate-700">{{ t.message }}</span>
        <button
          class="shrink-0 text-slate-400 hover:text-slate-600 transition-colors"
          @click="toastStore.remove(t.id)"
        >
          <X :size="14" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active { animation: toast-in 0.3s ease-out; }
.toast-leave-active { animation: toast-in 0.2s ease-in reverse; }
@keyframes toast-in {
  from { opacity: 0; transform: translateX(40px); }
  to { opacity: 1; transform: translateX(0); }
}
</style>
