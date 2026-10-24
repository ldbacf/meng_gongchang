<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
// 官方 viewer 组件：自带文本层（可选中/复制）、高亮、页码、缩放
import {
  EventBus,
  PDFViewer,
  PDFLinkService,
  PDFFindController,
} from 'pdfjs-dist/web/pdf_viewer.mjs'
import 'pdfjs-dist/web/pdf_viewer.css'
import { Minus, Plus, ChevronLeft, ChevronRight, Maximize2, AlertCircle } from 'lucide-vue-next'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  url: string
  title?: string
  /** 附加请求头（如 Authorization）——pdf.js 的 Range 请求也要带上鉴权 */
  headers?: Record<string, string>
  /** 需要在正文中高亮的片段（引用原文） */
  highlightText?: string | null
  /** 打开时定位到的页码（1-based） */
  initialPage?: number | null
}>()

const loading = ref(false)
const error = ref('')
const pageNum = ref(1)
const pageTotal = ref(0)
const scalePercent = ref(100)
const matchCount = ref(0)
const matchIndex = ref(0)
const highlightMissed = ref(false)

const containerRef = ref<HTMLElement | null>(null)
const viewerElRef = ref<HTMLElement | null>(null)

let eventBus: any = null
let linkService: any = null
let findController: any = null
let viewer: any = null
let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null
/** pagesinit 之前设 currentPageNumber 会报 "is not a valid page"，先存起来 */
let pendingPage: number | null = null

// ── 初始化 viewer（只需一次）──

function ensureViewer() {
  if (viewer || !containerRef.value || !viewerElRef.value) return
  eventBus = new EventBus()
  linkService = new PDFLinkService({ eventBus })
  findController = new PDFFindController({ eventBus, linkService })

  viewer = new PDFViewer({
    // pdf.js 的类型要求 HTMLDivElement；ref 声明为 HTMLElement，这里收窄
    container: containerRef.value as HTMLDivElement,
    viewer: viewerElRef.value as HTMLDivElement,
    eventBus,
    linkService,
    findController,
    // 只读预览：不启用编辑/注释层
    annotationMode: 0,
  })
  linkService.setViewer(viewer)

  eventBus.on('pagechanging', (e: any) => {
    pageNum.value = e.pageNumber
  })
  eventBus.on('pagesinit', () => {
    pageTotal.value = viewer.pagesCount
    viewer.currentScaleValue = 'page-width'
    // 页码与高亮都要等 pagesinit（页容器就绪）之后再处理
    if (pendingPage && pendingPage > 1) {
      viewer.currentPageNumber = Math.min(pendingPage, viewer.pagesCount)
    }
    pendingPage = null
    // 文本层是懒加载的，稍等一拍再搜，否则 find 可能扫不到内容
    setTimeout(() => runHighlight(), 350)
  })
  eventBus.on('scalechanging', (e: any) => {
    scalePercent.value = Math.round(e.scale * 100)
  })
  eventBus.on('updatefindmatchescount', (e: any) => {
    matchCount.value = e.matchesCount?.total ?? 0
  })
  eventBus.on('updatefindcontrolstate', (e: any) => {
    // state 1 = FOUND
    if (e.state === 1) matchIndex.value = (e.matchesCount?.current ?? 0) + 1
  })
}

// ── 从引用片段推导一个可命中文本层的查询串 ──
//
// 文本层与 MinerU 抽取的文本在标点、空格上并不一致，直接拿整段 snippet 搜
// 几乎必然 0 命中。策略：只在**标点**处切段（不能按空格切，否则英文会被拆成
// 单个单词），取最长的无标点片段作为查询。
function buildQuery(snippet: string): string {
  const segs = snippet
    .split(/[，。、；：！？""''（）()《》〈〉【】\[\]…—\-–·,.;:!?"'`]+/)
    .map((s) => s.replace(/\s+/g, ' ').trim())
    .filter((s) => s.replace(/\s/g, '').length >= 8)

  if (segs.length) {
    const best = segs.reduce((a, b) => (b.length > a.length ? b : a))
    return best.slice(0, 60)
  }
  // 兜底：整段去掉标点后取前 20 字
  const cleaned = snippet.replace(/[^\u4e00-\u9fa5A-Za-z0-9 ]/g, '').replace(/\s+/g, ' ').trim()
  return cleaned.slice(0, 20)
}

function runHighlight() {
  const text = props.highlightText?.trim()
  if (!text || !eventBus) {
    highlightMissed.value = false
    return
  }
  const query = buildQuery(text)
  if (!query) {
    highlightMissed.value = true
    return
  }
  highlightMissed.value = false
  matchCount.value = 0
  matchIndex.value = 0

  eventBus.dispatch('find', {
    source: null,
    type: '',
    query,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: false,
    matchDiacritics: false,
  })

  // find 是异步的：等文本层高亮落地后再判断是否命中
  setTimeout(() => {
    highlightMissed.value = matchCount.value === 0
  }, 900)
}

// ── 加载 ──

async function loadPdf() {
  loading.value = true
  error.value = ''
  pageNum.value = 1
  pageTotal.value = 0
  matchCount.value = 0
  highlightMissed.value = false

  await nextTick()
  ensureViewer()

  try {
    if (pdfDoc) {
      pdfDoc.destroy()
      pdfDoc = null
    }

    const task = pdfjsLib.getDocument({
      url: props.url,
      httpHeaders: props.headers,
      rangeChunkSize: 128 * 1024,
      // pdf.js 必先发一个无 Range 的探测请求；disableStream=true 才会在确认支持
      // 分片后立即 cancel 它，否则白拉一整份（见 HAR 分析）。
      disableStream: true,
      disableAutoFetch: true,
    })

    pdfDoc = await task.promise
    pendingPage = props.initialPage ?? null
    viewer.setDocument(pdfDoc)
    linkService.setDocument(pdfDoc, null)
    loading.value = false

    await nextTick()
  } catch (e) {
    console.error('PDF load error:', e)
    error.value = 'PDF 加载失败，请检查文件是否有效'
    loading.value = false
  }
}

// ── 工具栏 ──

function goPrev() { if (viewer && pageNum.value > 1) viewer.currentPageNumber = pageNum.value - 1 }
function goNext() { if (viewer && pageNum.value < pageTotal.value) viewer.currentPageNumber = pageNum.value + 1 }
function zoomOut() { if (viewer) viewer.currentScale = Math.max(0.25, viewer.currentScale / 1.15) }
function zoomIn() { if (viewer) viewer.currentScale = Math.min(4, viewer.currentScale * 1.15) }
function fitWidth() { if (viewer) viewer.currentScaleValue = 'page-width' }

function nextMatch() {
  if (!eventBus) return
  eventBus.dispatch('find', {
    source: null, type: 'again', query: '', caseSensitive: false,
    entireWord: false, highlightAll: true, findPrevious: false,
  })
}

// ── 生命周期 ──

onMounted(() => { loadPdf() })
watch(() => props.url, () => { loadPdf() })
watch(() => props.highlightText, () => { if (pdfDoc) runHighlight() })

onBeforeUnmount(() => {
  if (pdfDoc) { pdfDoc.destroy(); pdfDoc = null }
  viewer = null
  eventBus = null
})
</script>

<template>
  <div class="flex h-full flex-col bg-surface">
    <!-- 工具栏 -->
    <div class="flex items-center gap-1 border-b border-line bg-surface-2 px-2 py-1.5">
      <button
        class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink disabled:opacity-40"
        :disabled="pageNum <= 1 || !pageTotal"
        title="上一页"
        @click="goPrev"
      >
        <ChevronLeft :size="15" />
      </button>
      <span class="min-w-[54px] text-center font-mono text-[11.5px] tabular-nums text-muted">
        {{ pageNum }} / {{ pageTotal || '—' }}
      </span>
      <button
        class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink disabled:opacity-40"
        :disabled="pageNum >= pageTotal || !pageTotal"
        title="下一页"
        @click="goNext"
      >
        <ChevronRight :size="15" />
      </button>

      <span class="mx-1 h-4 w-px bg-line" />

      <button class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink" title="缩小" @click="zoomOut">
        <Minus :size="14" />
      </button>
      <span class="min-w-[42px] text-center font-mono text-[11.5px] tabular-nums text-muted">{{ scalePercent }}%</span>
      <button class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink" title="放大" @click="zoomIn">
        <Plus :size="14" />
      </button>
      <button class="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink" title="适应宽度" @click="fitWidth">
        <Maximize2 :size="13" />
      </button>

      <!-- 命中提示 -->
      <button
        v-if="highlightText && matchCount > 0"
        class="ml-auto flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10.5px] font-medium text-accent-text"
        title="跳到下一处匹配"
        @click="nextMatch"
      >
        命中 {{ matchIndex || 1 }}/{{ matchCount }}
      </button>
      <span
        v-else-if="highlightMissed"
        class="ml-auto text-[10.5px] text-warn"
        title="文本层未匹配到该片段：MinerU 抽取文本与 PDF 排版可能不一致"
      >未定位到原文</span>
    </div>

    <!-- 画布 -->
    <div class="relative flex-1 overflow-hidden">
      <div v-if="loading" class="absolute inset-0 z-10 grid place-items-center bg-surface">
        <div class="flex items-center gap-2 text-[12.5px] text-muted">
          <span class="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          加载 PDF…
        </div>
      </div>

      <div v-if="error" class="absolute inset-0 z-10 grid place-items-center bg-surface px-6">
        <div class="flex items-center gap-2 text-[12.5px] text-danger">
          <AlertCircle :size="15" />
          {{ error }}
        </div>
      </div>

      <!-- pdf.js 要求 container 的计算样式为 position:absolute（它自己做滚动），
           否则构造函数直接抛 "The `container` must be absolutely positioned." -->
      <div ref="containerRef" class="pdf-scroll absolute inset-0 overflow-auto">
        <div ref="viewerElRef" class="pdfViewer" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 官方 viewer 的页面阴影偏重，压平到与整体风格一致 */
.pdf-scroll :deep(.pdfViewer) {
  padding: 12px 8px 20px;
}

.pdf-scroll :deep(.pdfViewer .page) {
  margin: 0 auto 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: var(--sh-1);
}

/* 高亮：两个 CSS 变量是声明在 `.textLayer .highlight` **自己身上**的（不是继承），
   所以必须在同一元素上覆盖；默认值是品红 + 选中绿，与整体配色不搭。 */
.pdf-scroll :deep(.textLayer .highlight) {
  --highlight-bg-color: rgba(26, 115, 232, 0.25);
  --highlight-selected-bg-color: rgba(26, 115, 232, 0.45);
  border-radius: 2px;
}

.pdf-scroll :deep(.textLayer) {
  user-select: text;
}
</style>
