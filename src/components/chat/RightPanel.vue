<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Citation } from '@/types'
import VuePdfEmbed from 'vue-pdf-embed'
import { X, ArrowLeft, FileText, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  citations: Citation[]
  activeCitation: Citation | null
  pdfUrl: string | null
  pdfLoading: boolean
}>()

const emit = defineEmits<{
  close: []
  'back-to-list': []
  'select-citation': [citation: Citation]
}>()

const currentPage = ref(1)

watch(
  () => props.activeCitation,
  () => {
    currentPage.value = 1
  },
)
</script>

<template>
  <aside
    class="flex h-full w-[420px] shrink-0 flex-col border-l bg-white shadow-lg"
  >
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-5 py-4">
      <span class="text-base font-semibold text-slate-800">
        文献资源库
      </span>
      <button
        class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
        @click="emit('close')"
      >
        <X :size="18" />
      </button>
    </div>

    <!-- Body -->
    <div class="relative flex-1 overflow-hidden">
      <!-- LIST layer -->
      <div
        v-if="!activeCitation"
        class="absolute inset-0 overflow-y-auto px-5 py-4 space-y-4"
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

      <!-- DETAIL overlay -->
      <div
        v-if="activeCitation"
        class="absolute inset-0 z-10 flex flex-col bg-white"
      >
        <!-- Detail header -->
        <div class="border-b px-5 py-3">
          <button
            class="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
            @click="emit('back-to-list')"
          >
            <ArrowLeft :size="14" />
            返回文献列表
          </button>
        </div>

        <!-- PDF viewer -->
        <div class="flex-1 overflow-auto bg-slate-100">
          <div v-if="pdfLoading" class="flex items-center justify-center py-20">
            <Loader2 :size="24" class="animate-spin text-blue-500" />
            <span class="ml-2 text-sm text-slate-500">加载 PDF...</span>
          </div>
          <div
            v-else-if="pdfUrl"
            class="pdf-container h-full"
          >
            <VuePdfEmbed
              :source="pdfUrl"
              :page="currentPage"
              text-layer
              annotation-layer
              class="h-full"
            />
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.pdf-container :deep(canvas) {
  max-width: 100%;
}
</style>
