<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Upload, Trash2, FileText, AlertCircle, CheckCircle2, Loader2 } from 'lucide-vue-next'
import { useAdminStore } from '@/stores/admin'
import type { Document, DocumentStatus } from '@/types'

const adminStore = useAdminStore()
const fileInput = ref<HTMLInputElement | null>(null)

onMounted(() => {
  adminStore.fetchDocuments()
})

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await adminStore.uploadDocument(file)
  input.value = ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const statusConfig: Record<DocumentStatus, { label: string; color: string; icon: unknown }> = {
  uploading: { label: '上传中', color: 'text-amber-500', icon: Loader2 },
  chunking: { label: '分块中', color: 'text-blue-500', icon: Loader2 },
  embedding: { label: '向量化', color: 'text-purple-500', icon: Loader2 },
  ready: { label: '就绪', color: 'text-emerald-500', icon: CheckCircle2 },
  error: { label: '失败', color: 'text-red-500', icon: AlertCircle },
}

function statusLabel(status: DocumentStatus) {
  return statusConfig[status].label
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-6 py-4">
      <div>
        <h1 class="text-lg font-semibold text-slate-800">知识库管理</h1>
        <p class="text-sm text-slate-500">管理医学文献文档，上传并追踪向量化进度</p>
      </div>
      <button
        class="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors shadow-sm"
        @click="triggerUpload"
      >
        <Upload :size="16" />
        上传文档
      </button>
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.txt,.doc,.docx,.md"
        class="hidden"
        @change="handleFileChange"
      />
    </div>

    <!-- Document List -->
    <div class="flex-1 overflow-y-auto p-6">
      <div v-if="adminStore.documents.length === 0" class="flex flex-col items-center justify-center py-20 text-slate-400">
        <FileText :size="48" class="mb-4" />
        <p class="text-sm">暂无上传文档</p>
        <p class="text-xs mt-1">点击"上传文档"添加医学文献</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="doc in adminStore.documents"
          :key="doc.id"
          class="flex items-center gap-4 rounded-xl border bg-white p-4 transition-all hover:shadow-sm"
        >
          <!-- File icon -->
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100">
            <FileText :size="20" class="text-slate-500" />
          </div>

          <!-- Info -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-slate-800 truncate">{{ doc.name }}</p>
            <div class="mt-1 flex items-center gap-3">
              <span class="text-xs text-slate-400">{{ formatSize(doc.size) }}</span>
              <span
                class="flex items-center gap-1 text-xs"
                :class="statusConfig[doc.status].color"
              >
                <component
                  :is="statusConfig[doc.status].icon"
                  :size="14"
                  :class="{ 'animate-spin': doc.status !== 'ready' && doc.status !== 'error' }"
                />
                {{ statusLabel(doc.status) }}
              </span>
            </div>

            <!-- Progress bar -->
            <div
              v-if="doc.status !== 'ready' && doc.status !== 'error'"
              class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100"
            >
              <div
                class="h-full rounded-full bg-primary-500 transition-all duration-500"
                :style="{ width: `${doc.progress}%` }"
              />
            </div>
          </div>

          <!-- Delete -->
          <button
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500 transition-colors"
            @click="adminStore.deleteDocument(doc.id)"
          >
            <Trash2 :size="16" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
