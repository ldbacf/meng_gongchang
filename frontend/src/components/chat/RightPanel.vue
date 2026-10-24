<script setup lang="ts">
import type { Citation } from '@/types'
import PdfViewer from './PdfViewer.vue'
import { X, ArrowLeft, FileText, Loader2 } from 'lucide-vue-next'

defineProps<{
  citations: Citation[]
  activeCitation: Citation | null
  pdfUrl: string | null
  pdfLoading: boolean
  showBackButton: boolean
  /** pdf.js Range 请求所需的附加头（Authorization） */
  pdfHeaders?: Record<string, string>
}>()

const emit = defineEmits<{
  close: []
  'back-to-list': []
  'select-citation': [citation: Citation]
}>()
</script>

<template>
  <!-- 覆盖式侧栏：不挤压消息列宽（Gemini 的引用面板就是浮层） -->
  <aside
    class="absolute inset-y-0 right-0 z-30 flex w-[560px] max-w-[92vw] flex-col border-l border-line bg-surface-2 shadow-lg"
  >
    <div class="flex items-center gap-2 border-b border-line px-3 py-3">
      <button
        v-if="activeCitation && showBackButton"
        class="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
        title="返回列表"
        @click="emit('back-to-list')"
      >
        <ArrowLeft :size="16" />
      </button>
      <div class="min-w-0 flex-1 truncate text-[13.5px] font-semibold">
        {{ activeCitation ? activeCitation.title : '参考文献' }}
      </div>
      <button
        class="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
        title="关闭"
        @click="emit('close')"
      >
        <X :size="17" />
      </button>
    </div>

    <div class="flex-1 overflow-hidden">
      <!-- 列表 -->
      <div v-if="!activeCitation" class="h-full overflow-y-auto px-4 py-4">
        <p v-if="!citations.length" class="py-16 text-center text-[12.5px] text-faint">
          暂无参考文献
        </p>
        <button
          v-for="cite in citations"
          :key="cite.id + ':' + (cite.doc_id ?? '')"
          class="mb-2.5 block w-full rounded-xl border border-line bg-canvas px-3.5 py-3 text-left transition-all hover:border-line-strong hover:bg-surface hover:shadow-sm"
          @click="emit('select-citation', cite)"
        >
          <div class="mb-1.5 flex items-start gap-2">
            <span class="mt-px grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-[5px] bg-accent-soft px-1 text-[10.5px] font-bold text-accent-text">
              {{ cite.id }}
            </span>
            <p class="line-clamp-2 text-[13px] font-semibold leading-snug">{{ cite.title }}</p>
          </div>
          <p class="mb-2 line-clamp-2 text-[11.5px] leading-relaxed text-muted">{{ cite.snippet }}</p>
          <span class="inline-flex items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-[10.5px] text-muted">
            <FileText :size="9" />
            {{ cite.source || '中国全科医学' }}
          </span>
        </button>
      </div>

      <!-- 详情（PDF） -->
      <div v-else class="flex h-full flex-col">
        <div class="flex-1 overflow-hidden bg-surface">
          <div v-if="pdfLoading" class="flex h-full items-center justify-center gap-2">
            <Loader2 :size="18" class="animate-spin text-accent" />
            <span class="text-[12.5px] text-muted">加载 PDF…</span>
          </div>
          <PdfViewer
            v-else-if="pdfUrl"
            :url="pdfUrl"
            :title="activeCitation?.title"
            :headers="pdfHeaders"
            :highlight-text="activeCitation?.snippet ?? null"
            :initial-page="activeCitation?.page ?? null"
          />
          <div v-else class="flex h-full items-center justify-center text-[12.5px] text-faint">
            该文献暂无可预览的原文
          </div>
        </div>
        <div class="border-t border-line px-4 py-3">
          <p class="text-[11.5px] leading-relaxed text-muted">
            {{ activeCitation.snippet }}
          </p>
        </div>
      </div>
    </div>
  </aside>
</template>
