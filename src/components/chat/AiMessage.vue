<script setup lang="ts">
import type { Message } from '@/types'
import { useMarkdown } from '@/composables/useMarkdown'
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useChatStore } from '@/stores/chat'
import RagPipelineSimple from './RagPipelineSimple.vue'
import CitationSummary from './CitationSummary.vue'
import { Sparkles, ChevronDown, AlertCircle, Copy, Check } from 'lucide-vue-next'

const chatStore = useChatStore()

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
}>()

const emit = defineEmits<{
  'citation-click': [id: string]
  'show-citation-list': []
}>()

const { render } = useMarkdown()

const renderedContent = computed(() => {
  const content =
    props.isStreaming && props.streamContent !== undefined
      ? props.streamContent
      : props.message.content
  return render(content)
})

function handleContentClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('.citation-tag') as HTMLElement | null
  if (target?.dataset.citationId) {
    emit('citation-click', target.dataset.citationId)
  }
}

const copied = ref(false)

async function copyContent() {
  const text = props.isStreaming && props.streamContent !== undefined ? props.streamContent : props.message.content
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* fallback */ }
}

const hasRagSteps = computed(() => {
  const steps = props.message.ragSteps
  return steps && Object.values(steps).some((s) => s !== undefined)
})

// ── Run status ──

const isProcessing = computed(() => {
  const steps = props.message.ragSteps
  if (!steps) return false
  const vals = Object.values(steps)
  return vals.some((s) => s?.status === 'pending')
})

// ── Random text rotation ──

const statusPhrases = [
  '正在理解问题...',
  '检索文献中...',
  '分析医学资料...',
  '梳理临床信息...',
  '生成医学回答...',
  '查阅知识库...',
  '推理分析中...',
]

const currentPhrase = ref('')
let phraseTimer: ReturnType<typeof setInterval> | undefined
let lastIndex = -1

function pickRandomPhrase() {
  let idx: number
  do {
    idx = Math.floor(Math.random() * statusPhrases.length)
  } while (idx === lastIndex && statusPhrases.length > 1)
  lastIndex = idx
  currentPhrase.value = statusPhrases[idx]
}

function startPhraseRotation() {
  pickRandomPhrase()
  if (!phraseTimer) {
    phraseTimer = setInterval(pickRandomPhrase, 2000)
  }
}

function stopPhraseRotation() {
  if (phraseTimer) {
    clearInterval(phraseTimer)
    phraseTimer = undefined
  }
  currentPhrase.value = ''
}

// Watch processing state
watch(isProcessing, (processing) => {
  if (processing) {
    startPhraseRotation()
  } else {
    stopPhraseRotation()
  }
}, { immediate: true })

onBeforeUnmount(() => {
  stopPhraseRotation()
})

// ── Persistent expand toggle ──

const ragExpanded = ref(localStorage.getItem('medrag_rag_expanded') !== 'false')
function toggleRag() {
  ragExpanded.value = !ragExpanded.value
  localStorage.setItem('medrag_rag_expanded', String(ragExpanded.value))
}
</script>

<template>
  <div class="group px-4 py-4">
    <div class="flex max-w-[85%] gap-3">
      <!-- Avatar -->
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-sky-400 shadow-sm"
      >
        <Sparkles :size="16" class="text-white" />
      </div>

      <!-- Right column -->
      <div class="min-w-0 flex-1">
        <!-- Thinking pill -->
        <button
          v-if="hasRagSteps"
          class="mb-2 inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium shadow-sm transition-all duration-200 hover:scale-105 focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:outline-none"
          :class="{
            'animate-breathe border-primary-400 bg-primary-50 text-primary-700': isProcessing,
            'border-primary-200 bg-primary-50/70 text-primary-700 hover:border-primary-300 hover:bg-primary-100': !isProcessing,
          }"
          @click="toggleRag"
        >
          <Sparkles
            :size="13"
            :class="{ 'animate-spin': isProcessing }"
          />
          <span v-if="isProcessing && currentPhrase">{{ currentPhrase }}</span>
          <span v-else>RAG 检索分析</span>
          <ChevronDown
            :size="13"
            class="transition-transform duration-200"
            :class="{ 'rotate-180': ragExpanded }"
          />
        </button>

        <!-- RAG Pipeline -->
        <RagPipelineSimple
          v-if="ragExpanded && hasRagSteps"
          :steps="message.ragSteps!"
        />

        <!-- Content card -->
        <div
          class="rounded-2xl border border-primary-300 bg-primary-100 px-4 py-3 shadow-md backdrop-blur-sm"
        >
          <div
            v-if="renderedContent"
            class="markdown-body text-sm leading-relaxed text-slate-700"
            v-html="renderedContent"
            @click="handleContentClick"
          />

          <!-- Copy button -->
          <div class="mt-1 flex justify-end opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-hover:duration-100">
            <button
              class="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-primary-200 hover:text-slate-600 active:scale-90"
              title="复制回答"
              @click="copyContent"
            >
              <Check v-if="copied" :size="12" class="text-emerald-500" />
              <Copy v-else :size="12" />
            </button>
          </div>

          <div
            v-if="isStreaming && !streamContent"
            class="flex items-center gap-1 py-1"
          >
            <span class="h-2 w-2 animate-bounce rounded-full bg-primary-400" style="animation-delay: 0ms" />
            <span class="h-2 w-2 animate-bounce rounded-full bg-primary-400" style="animation-delay: 150ms" />
            <span class="h-2 w-2 animate-bounce rounded-full bg-primary-400" style="animation-delay: 300ms" />
          </div>
        </div>
        <div
          v-if="chatStore.streamError"
          class="mt-2 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2"
        >
          <AlertCircle :size="14" class="mt-0.5 shrink-0 text-red-400" />
          <p class="text-xs text-red-600 leading-relaxed">{{ chatStore.streamError }}</p>
        </div>
        <CitationSummary
          v-if="message.citations && !isStreaming"
          :citations="message.citations"
          @select-citation="(cite) => emit('citation-click', cite.id)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes breathe {
  0%, 100% {
    border-color: #93c5fd;
    box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.1), 0 2px 4px -2px rgba(59, 130, 246, 0.1);
  }
  50% {
    border-color: #60a5fa;
    box-shadow: 0 4px 14px -1px rgba(59, 130, 246, 0.25), 0 2px 8px -2px rgba(59, 130, 246, 0.15);
  }
}

.animate-breathe {
  animation: breathe 2s ease-in-out infinite;
}
</style>
