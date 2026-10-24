<script setup lang="ts">
import type { Citation } from '@/types'
import { computed, onBeforeUnmount, ref } from 'vue'
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

// ── 面板宽度：可拖拽 + 记忆 ────────────────────────────────

const MIN_W = 380
const DEFAULT_W = 560
const STORAGE_KEY = 'medrag_pdf_panel_width'

function readStored(): number {
  const raw = Number(localStorage.getItem(STORAGE_KEY))
  return Number.isFinite(raw) && raw >= MIN_W ? raw : DEFAULT_W
}

const width = ref(readStored())
const dragging = ref(false)
let startX = 0
let startW = 0

/** 上限取 92vw，且至少留 320px 给左侧内容，避免把聊天区挤没 */
function maxWidth(): number {
  return Math.max(MIN_W, Math.min(window.innerWidth * 0.92, window.innerWidth - 320))
}

function clamp(v: number): number {
  return Math.min(maxWidth(), Math.max(MIN_W, v))
}

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  startX = e.clientX
  startW = width.value
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  // 拖拽期间禁掉文字选中，否则鼠标一划过整页文字都被刷蓝
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  e.preventDefault()
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  // 往左拖 = 变宽，所以是 startX - clientX
  width.value = clamp(startW + (startX - e.clientX))
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  localStorage.setItem(STORAGE_KEY, String(Math.round(width.value)))
  // pdf.js 只在 window resize 时重算 page-width；面板变宽不会触发，
  // 手动派发一次让它重新适配（否则拖完页面还是旧宽度，右侧出现空白/裁切）
  window.dispatchEvent(new Event('resize'))
}

/** 双击恢复默认宽度 */
function resetWidth() {
  width.value = clamp(DEFAULT_W)
  localStorage.setItem(STORAGE_KEY, String(Math.round(width.value)))
}

/** 键盘微调（无障碍）：左右方向键 ±24px */
function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  width.value = clamp(width.value + (e.key === 'ArrowLeft' ? 24 : -24))
  localStorage.setItem(STORAGE_KEY, String(Math.round(width.value)))
}

// 窗口变窄时把面板收回合法区间
function onWindowResize() {
  width.value = clamp(width.value)
}
window.addEventListener('resize', onWindowResize)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
})

const panelStyle = computed(() => ({
  width: `${width.value}px`,
  // 小屏（<=980px）时让 CSS 的 max-w-[92vw] 接管
  maxWidth: '92vw',
  // 拖拽时关掉过渡（否则宽度变化会跟手有延迟）；
  // 其余情况交给 .panel-enter/leave 的类控制，不要用内联样式覆盖
  transition: dragging.value ? 'none' : undefined,
}))
</script>

<template>
  <!-- 覆盖式侧栏：不挤压消息列宽（Gemini 的引用面板就是浮层） -->
  <aside
    class="absolute inset-y-0 right-0 z-30 flex flex-col border-l border-line bg-surface-2 shadow-lg"
    :style="panelStyle"
  >
    <!-- 拖拽条：骑在左边框上，左右各露出 3px -->
    <div
      class="group absolute inset-y-0 left-0 z-10 w-[7px] -translate-x-1/2 cursor-col-resize touch-none select-none"
      role="separator"
      aria-orientation="vertical"
      aria-label="拖动调整面板宽度"
      tabindex="0"
      title="拖动调整宽度 · 双击恢复默认"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="resetWidth"
      @keydown="onKeydown"
    >
      <!-- 视觉反馈：hover / 拖拽时显出一道强调色 -->
      <div
        class="mx-auto h-full w-[2px] rounded-full transition-colors"
        :class="dragging ? 'bg-accent' : 'bg-transparent group-hover:bg-accent/60'"
      />
    </div>

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
