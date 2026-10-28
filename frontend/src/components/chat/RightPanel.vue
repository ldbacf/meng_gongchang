<script setup lang="ts">
import type { Citation } from '@/types'
import type { CitationBox, EvidenceResponse } from '@/api/citation'
import { computed, onBeforeUnmount, ref } from 'vue'
import PdfViewer from './PdfViewer.vue'
import EvidenceCard from './EvidenceCard.vue'
import { X, ArrowLeft, FileText, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  citations: Citation[]
  activeCitation: Citation | null
  pdfUrl: string | null
  pdfLoading: boolean
  showBackButton: boolean
  /** pdf.js Range 请求所需的附加头（Authorization） */
  pdfHeaders?: Record<string, string>
  /** 引用在原文中的精确位置（后端 bbox 定位结果） */
  highlightBoxes?: CitationBox[] | null
  /** 定位失败时的说明；空字符串表示无异常 */
  locateMessage?: string
  /** 证据卡数据（摘要分段 / 样本量 / 连续上下文） */
  evidence?: EvidenceResponse | null
  evidenceLoading?: boolean
  /** 详情区视图：证据卡在前，PDF 是「查看原文」之后的第二层 */
  view?: 'evidence' | 'pdf'
}>()

const emit = defineEmits<{
  close: []
  'back-to-list': []
  'select-citation': [citation: Citation]
  'open-pdf': []
  'show-evidence': []
}>()

/**
 * 证据卡 ↔ PDF 切换。
 *
 * 写成具名函数而不是内联三元：`emit('a'|'b')` 的联合类型参数
 * 在 vue-tsc 下会报「No overload matches」，且内联可读性也差。
 */
function toggleView() {
  if (props.view === 'pdf') emit('show-evidence')
  else emit('open-pdf')
}

// ── 面板宽度：可拖拽 + 记忆 ────────────────────────────────
//
// MIN_W 从 380 提到 440、默认 560 → 600：证据卡正文用 15px / 行高 1.95，
// 380px 宽时一行只放得下约 22 个汉字，读三段摘要就开始频繁跳行。
// 读者反馈的"拥挤"不是信息太多，是行宽不够 —— 所以放宽面板，
// 而不是把字号压小去迁就窄栏。

const MIN_W = 440
const DEFAULT_W = 600
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
      <!-- 证据卡 ↔ PDF 切换：只在有 PDF 且正在看详情时出现 -->
      <button
        v-if="activeCitation && pdfUrl"
        class="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition-colors hover:bg-surface hover:text-ink"
        :title="view === 'pdf' ? '返回证据卡' : '查看原文 PDF'"
        @click="toggleView"
      >
        <FileText v-if="view !== 'pdf'" :size="11" />
        <ArrowLeft v-else :size="11" />
        {{ view === 'pdf' ? '证据卡' : '原文' }}
      </button>
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

      <!-- 详情 -->
      <div v-else class="flex h-full flex-col">
        <!-- 证据卡（默认视图）：摘要分段 + 连续上下文，毫秒级、不等 PDF -->
        <div v-if="view !== 'pdf'" class="min-h-0 flex-1 overflow-hidden">
          <EvidenceCard
            :evidence="evidence ?? null"
            :loading="evidenceLoading ?? false"
            :snippet="activeCitation?.snippet ?? ''"
          />
        </div>

        <!-- PDF（第二层：用户明确要看原文时才加载，2.76MB @240KB/s ≈ 12s） -->
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
              :highlight-boxes="highlightBoxes"
              :initial-page="activeCitation?.page ?? null"
            />
            <div v-else class="flex h-full items-center justify-center text-[12.5px] text-faint">
              该文献暂无可预览的原文
            </div>
          </div>
          <div class="border-t border-line px-4 py-3">
            <!-- 定位失败时说明原因，但 PDF 仍可正常阅读 -->
            <p
              v-if="locateMessage"
              class="mb-1.5 flex items-center gap-1.5 text-[10.5px] text-warn"
              title="后端未能在 MinerU 解析结果中匹配到该片段"
            >
              <span class="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
              {{ locateMessage }}
            </p>
            <p class="text-[11.5px] leading-relaxed text-muted">
              {{ activeCitation.snippet }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
