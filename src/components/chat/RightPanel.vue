<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import type { Citation } from '@/types'
import PdfViewer from './PdfViewer.vue'
import { X, ArrowLeft, FileText, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  citations: Citation[]
  activeCitation: Citation | null
  pdfUrl: string | null
  pdfLoading: boolean
  showBackButton: boolean
}>()

const emit = defineEmits<{
  close: []
  'back-to-list': []
  'select-citation': [citation: Citation]
}>()

// ── Resizable panel ──

const panelWidth = ref(630)
const MIN_WIDTH = 300
const MAX_WIDTH = 720
const isResizing = ref(false)

function onResizeStart(e: MouseEvent) {
  e.preventDefault()
  isResizing.value = true
  const startX = e.clientX
  const startWidth = panelWidth.value

  function onMouseMove(ev: MouseEvent) {
    const delta = startX - ev.clientX
    panelWidth.value = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + delta))
  }

  function onMouseUp() {
    isResizing.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

onBeforeUnmount(() => {
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<template>
  <aside
    class="relative flex h-full shrink-0 flex-col border-l bg-white shadow-lg"
    :class="{ 'select-none': isResizing }"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- Resize handle (left edge) -->
    <div
      class="absolute left-0 top-0 z-20 h-full w-1.5 cursor-col-resize hover:bg-blue-400/50 transition-colors"
      :class="isResizing ? 'bg-blue-500' : ''"
      style="margin-left: -3px"
      @mousedown="onResizeStart"
    />

    <!-- Header -->
    <div class="flex items-center justify-between border-b px-5 py-4">
      <span class="text-base font-semibold text-slate-800">
        引用文献
      </span>
      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
        @click="emit('close')"
      >
        <X :size="18" />
      </button>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-hidden">
      <!-- LIST layer -->
      <div
        v-if="!activeCitation"
        class="h-full overflow-y-auto px-5 py-4 space-y-4"
      >
        <div
          v-for="cite in citations"
          :key="cite.id"
          class="cursor-pointer rounded-xl border bg-slate-50 p-4 transition-all hover:border-blue-200 hover:bg-blue-50/30 hover:shadow-sm"
          @click="emit('select-citation', cite)"
        >
          <p class="mb-1.5 text-sm font-semibold text-slate-800">
            {{ cite.title }}
          </p>
          <p class="mb-2 text-xs leading-relaxed text-slate-500 line-clamp-3">
            {{ cite.snippet }}
          </p>
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              <FileText :size="10" />
              {{ cite.source }}
            </span>
            <span v-if="cite.page" class="text-xs text-slate-400">
              P.{{ cite.page }}
            </span>
          </div>
        </div>

        <div
          v-if="citations.length === 0"
          class="flex flex-col items-center justify-center py-20 text-slate-400"
        >
          <FileText :size="40" class="mb-3" />
          <p class="text-sm">暂无参考文献</p>
        </div>
      </div>

      <!-- DETAIL layer -->
      <div
        v-else
        class="flex h-full flex-col bg-white"
      >
        <div v-if="showBackButton" class="border-b px-5 py-3">
          <button
            class="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
            @click="emit('back-to-list')"
          >
            <ArrowLeft :size="14" />
            返回文献列表
          </button>
        </div>

        <div class="flex-1 overflow-hidden bg-slate-100">
          <div v-if="pdfLoading" class="flex items-center justify-center py-20">
            <Loader2 :size="24" class="animate-spin text-blue-500" />
            <span class="ml-2 text-sm text-slate-500">加载 PDF...</span>
          </div>
          <PdfViewer
            v-else-if="pdfUrl"
            :url="pdfUrl"
            :title="activeCitation?.title"
          />
        </div>
      </div>
    </div>
  </aside>
</template>
