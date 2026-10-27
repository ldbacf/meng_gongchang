<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
// 官方 viewer 组件：自带文本层（可选中/复制）、页码、缩放
import {
  EventBus,
  PDFViewer,
  PDFLinkService,
} from 'pdfjs-dist/web/pdf_viewer.mjs'
import 'pdfjs-dist/web/pdf_viewer.css'
import { Minus, Plus, ChevronLeft, ChevronRight, Maximize2, AlertCircle } from 'lucide-vue-next'
import type { CitationBox } from '@/api/citation'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  url: string
  title?: string
  /** 附加请求头（如 Authorization）——pdf.js 的 Range 请求也要带上鉴权 */
  headers?: Record<string, string>
  /**
   * 引用在原文中的精确位置（来自后端 `/locate`，数据源是 MinerU 的 bbox）。
   *
   * **不再用 findController 搜索全文**：那要求先加载完整份 PDF（12s @ 240KB/s），
   * 且 MinerU 文本与 PDF 文本层标点不一致时必然 0 命中。现在直接按坐标画框。
   */
  highlightBoxes?: CitationBox[] | null
  /** 打开时定位到的页码（1-based）。优先用 highlightBoxes[0].page */
  initialPage?: number | null
}>()

const loading = ref(false)
const error = ref('')
const pageNum = ref(1)
const pageTotal = ref(0)
const scalePercent = ref(100)
/** 已画上的高亮框数量（用于工具栏提示） */
const boxCount = ref(0)

const containerRef = ref<HTMLElement | null>(null)
const viewerElRef = ref<HTMLElement | null>(null)

let eventBus: any = null
let linkService: any = null
let viewer: any = null
let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null
/** pagesinit 之前设 currentPageNumber 会报 "is not a valid page"，先存起来 */
let pendingPage: number | null = null

// ── 初始化 viewer（只需一次）──

function ensureViewer() {
  if (viewer || !containerRef.value || !viewerElRef.value) return
  eventBus = new EventBus()
  linkService = new PDFLinkService({ eventBus })

  viewer = new PDFViewer({
    // pdf.js 的类型要求 HTMLDivElement；ref 声明为 HTMLElement，这里收窄
    container: containerRef.value as HTMLDivElement,
    viewer: viewerElRef.value as HTMLDivElement,
    eventBus,
    linkService,
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
    // 页面已建好即可画框；不依赖文本层（bbox 是几何信息）
    nextTick(() => renderBoxes())
  })
  eventBus.on('scalechanging', (e: any) => {
    scalePercent.value = Math.round(e.scale * 100)
    // 缩放后页面尺寸变了，框要按新尺寸重画
    nextTick(() => renderBoxes())
  })
  // 滚动到新页时，该页的 DOM 可能刚建出来，补画一次
  eventBus.on('pagerendered', () => {
    renderBoxes()
  })
}

// ── 按 bbox 画高亮框 ──
//
// bbox 是 MinerU 输出的 0-1000 归一化坐标（相对页面宽高）。这里把它换算成
// 实际像素，覆盖在该页的 `.page` 元素上。
//
// **为什么用绝对定位覆盖层而不是改文本层**：
//   - 文本层是 pdf.js 生成的，结构与 MinerU 的分块不一致，没法对应
//   - 覆盖层与文本层互不干扰：复制/选中仍然正常
//   - 缩放时只需重算像素，不用重建 DOM
function renderBoxes() {
  const root: HTMLElement | null = viewerElRef.value
  if (!root) return

  // 清掉旧框
  root.querySelectorAll('.cite-box-layer').forEach((n) => n.remove())
  boxCount.value = 0

  const boxes = props.highlightBoxes
  if (!boxes?.length || !viewer) return

  // 按页分组
  const byPage = new Map<number, CitationBox[]>()
  for (const b of boxes) {
    if (!byPage.has(b.page)) byPage.set(b.page, [])
    byPage.get(b.page)!.push(b)
  }

  for (const [page, list] of byPage) {
    const pageEl = root.querySelector(`.page[data-page-number="${page}"]`) as HTMLElement | null
    if (!pageEl) continue  // 该页还没渲染（虚拟滚动），等 pagerendered 再来

    // 页面元素尺寸 = PDF 页在 100% 缩放下的尺寸 × 当前缩放；
    // 用 offsetWidth/Height 直接读实际布局尺寸最稳妥
    const w = pageEl.offsetWidth
    const h = pageEl.offsetHeight
    if (!w || !h) continue

    const layer = document.createElement('div')
    layer.className = 'cite-box-layer'
    // 覆盖层要盖在 canvas 之上、文本层之下（文本层仍需可选中）
    layer.style.cssText = [
      'position:absolute',
      'inset:0',
      'pointer-events:none',
      'z-index:2',
    ].join(';')

    for (const b of list) {
      const [x0, y0, x1, y1] = b.bbox
      const el = document.createElement('div')
      el.className = 'cite-box'
      el.style.cssText = [
        'position:absolute',
        `left:${(x0 / 1000) * w}px`,
        `top:${(y0 / 1000) * h}px`,
        `width:${((x1 - x0) / 1000) * w}px`,
        `height:${((y1 - y0) / 1000) * h}px`,
        'border-radius:2px',
        'background:var(--cite-hl-bg)',
        'box-shadow:0 0 0 2px var(--cite-hl-bg)',
        'animation:cite-in .45s cubic-bezier(.215,.61,.355,1) both',
      ].join(';')
      layer.appendChild(el)
    }

    pageEl.appendChild(layer)
    pageEl.style.position = 'relative'
    boxCount.value += list.length
  }
}

// ── 加载 ──

async function loadPdf() {
  loading.value = true
  error.value = ''
  pageNum.value = 1
  pageTotal.value = 0
  boxCount.value = 0

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
    // 定位页：highlightBoxes 的首页优先于外部传入的 initialPage
    pendingPage = props.highlightBoxes?.[0]?.page ?? props.initialPage ?? null
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

/** 跳到第一处命中（多命中时在工具栏提供切换） */
function gotoFirstBox() {
  const b = props.highlightBoxes?.[0]
  if (b && viewer) viewer.currentPageNumber = Math.min(b.page, viewer.pagesCount)
}

// ── 生命周期 ──

onMounted(() => { loadPdf() })
watch(() => props.url, () => { loadPdf() })
watch(
  () => props.highlightBoxes,
  () => {
    if (!pdfDoc) return
    const first = props.highlightBoxes?.[0]
    if (first && viewer && first.page !== pageNum.value) {
      viewer.currentPageNumber = Math.min(first.page, viewer.pagesCount)
    }
    nextTick(() => renderBoxes())
  },
  { deep: true },
)

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

      <!-- 命中提示：点击跳到第一处 -->
      <button
        v-if="boxCount > 0"
        class="ml-auto flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10.5px] font-medium text-accent-text"
        title="跳到命中位置"
        @click="gotoFirstBox"
      >
        已定位 {{ boxCount }} 处
      </button>
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

.pdf-scroll :deep(.textLayer) {
  user-select: text;
}

/* ── bbox 高亮框 ──
   颜色走 CSS 变量，明暗主题各自定义（在 tokens.css 里）。
   用半透明背景 + 同等 box-shadow 让边框与填充一致，视觉上是一块干净的色带。 */
.pdf-scroll :deep(.cite-box-layer) {
  --cite-hl-bg: rgba(26, 115, 232, 0.28);
}

:global(html.dark) .pdf-scroll :deep(.cite-box-layer) {
  --cite-hl-bg: rgba(138, 180, 248, 0.3);
}

@keyframes cite-in {
  from { opacity: 0; transform: scaleY(0.6); }
  to { opacity: 1; transform: none; }
}
</style>
