<script setup lang="ts">
import { ref } from 'vue'
import type { DocumentInfo } from '@/types/knowledge'
import { FileText, AlertCircle, CheckCircle2, Loader2 } from 'lucide-vue-next'

defineProps<{
  documents: DocumentInfo[]
}>()

defineEmits<{
  delete: [id: string]
}>()

const statusConfig: Record<string, { label: string; color: string; icon: unknown }> = {
  pending: { label: '等待中', color: 'text-slate-400', icon: Loader2 },
  processing: { label: '处理中', color: 'text-blue-500', icon: Loader2 },
  ready: { label: '就绪', color: 'text-emerald-500', icon: CheckCircle2 },
  failed: { label: '失败', color: 'text-red-500', icon: AlertCircle },
}
</script>
<template>
  <div class="space-y-3">
    <div v-for="doc in documents" :key="doc.id" class="flex items-center gap-4 rounded-xl border bg-white p-4 transition-all hover:shadow-sm">
      <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100">
        <FileText :size="20" class="text-slate-500" />
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium text-slate-800 truncate">{{ doc.original_name }}</p>
        <div class="mt-1 flex items-center gap-3">
          <span class="text-xs text-slate-400 font-mono">{{ doc.md5.slice(0, 8) }}</span>
          <span class="flex items-center gap-1 text-xs" :class="statusConfig[doc.status]?.color || 'text-slate-400'">
            <component :is="statusConfig[doc.status]?.icon || Loader2" :size="14"
              :class="{ 'animate-spin': doc.status !== 'ready' && doc.status !== 'failed' }" />
            {{ statusConfig[doc.status]?.label || doc.status }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
