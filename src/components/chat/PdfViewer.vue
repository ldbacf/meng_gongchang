<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Minus, Plus } from 'lucide-vue-next'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  url: string
  title?: string
}>()

const loading = ref(false)
const error = ref('')
const pageCount = ref(0)
const scale = ref(1.0)
const canvasWraps = ref<{ pageNum: number }[]>([])
const canvasRefs = new Map<number, HTMLCanvasElement>()

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null

// ── Load PDF as binary, then render ──

async function loadPdf() {
  loading.value = true
  error.value = ''
  canvasWraps.value = []
  canvasRefs.clear()
  if (pdfDoc) { pdfDoc.destroy(); pdfDoc = null }
  pageCount.value = 0

  try {
    const response = await fetch(props.url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)

    const loadingTask = pdfjsLib.getDocument({ data: uint8Array })
    pdfDoc = await loadingTask.promise
    pageCount.value = pdfDoc.numPages

    canvasWraps.value = Array.from({ length: pdfDoc.numPages }, (_, i) => ({
      pageNum: i + 1,
    }))

    loading.value = false
    await nextTick()
    // renderAllPages will be driven by getCanvasRef as canvases mount
  } catch (e) {
    console.error('PDF load error:', e)
    error.value = 'PDF 加载失败，请检查文件是否有效'
    loading.value = false
  }
}

// ── Canvas ref → queue render ──

function getCanvasRef(el: unknown, pageNum: number) {
  if (!(el instanceof HTMLCanvasElement)) return
  canvasRefs.set(pageNum, el)
  queueRender(pageNum, el)
}

const renderQueue = new Map<number, HTMLCanvasElement>()
let flushPending = false

function queueRender(pageNum: number, canvas: HTMLCanvasElement) {
  renderQueue.set(pageNum, canvas)
  scheduleFlush()
}

function scheduleFlush() {
  if (flushPending) return
  flushPending = true
  requestAnimationFrame(() => {
    flushPending = false
    flushRenderQueue()
  })
}

async function flushRenderQueue() {
  if (!pdfDoc || renderQueue.size === 0) return
  const entries = [...renderQueue.entries()]
  renderQueue.clear()

  for (const [pageNum, canvas] of entries) {
    try {
      const page = await pdfDoc.getPage(pageNum)
      const viewport = page.getViewport({ scale: scale.value })
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = viewport.width + 'px'
      canvas.style.height = viewport.height + 'px'
      await page.render({ canvas, viewport }).promise
    } catch {
      // skip
    }
  }
}

// ── Zoom ──

async function changeZoom(newScale: number) {
  if (newScale === scale.value) return
  scale.value = newScale
  if (pdfDoc && canvasWraps.value.length > 0) {
    for (const cw of canvasWraps.value) {
      const canvas = canvasRefs.get(cw.pageNum)
      if (canvas) queueRender(cw.pageNum, canvas)
    }
  }
}

function zoomAtPoint(oldScale: number, newScale: number, anchorX: number, anchorY: number) {
  const container = scrollRef.value
  if (!container) return
  const scrollLeft = container.scrollLeft
  const scrollTop = container.scrollTop

  changeZoom(newScale)

  requestAnimationFrame(() => {
    if (!container) return
    const ratio = newScale / oldScale
    container.scrollLeft = (scrollLeft + anchorX) * ratio - anchorX
    container.scrollTop = (scrollTop + anchorY) * ratio - anchorY
  })
}

function onWheel(e: WheelEvent) {
  if (!e.ctrlKey) return
  e.preventDefault()

  const oldScale = scale.value
  const newScale = Math.min(3, Math.max(0.5, +(oldScale + (e.deltaY < 0 ? 0.25 : -0.25)).toFixed(2)))
  if (newScale === oldScale) return

  const container = scrollRef.value
  const mouseX = container ? e.clientX - container.getBoundingClientRect().left : 0
  const mouseY = container ? e.clientY - container.getBoundingClientRect().top : 0

  zoomAtPoint(oldScale, newScale, mouseX, mouseY)
}

function toolbarZoom(delta: number) {
  const oldScale = scale.value
  const newScale = Math.min(3, Math.max(0.5, +(oldScale + delta).toFixed(2)))
  if (newScale === oldScale) return

  const container = scrollRef.value
  const cx = container ? container.clientWidth / 2 : 0
  const cy = container ? container.clientHeight / 2 : 0

  zoomAtPoint(oldScale, newScale, cx, cy)
}

// ── Drag-to-scroll ──

const isDragging = ref(false)
let dragStartX = 0
let dragStartY = 0
let scrollStartX = 0
let scrollStartY = 0
const scrollRef = ref<HTMLElement | null>(null)

function hasOverflow(el: HTMLElement): boolean {
  return el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight
}

function onMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  const el = scrollRef.value
  if (!el || !hasOverflow(el)) return
  isDragging.value = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  scrollStartX = el.scrollLeft
  scrollStartY = el.scrollTop
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const dx = dragStartX - e.clientX
  const dy = dragStartY - e.clientY
  if (scrollRef.value) {
    scrollRef.value.scrollLeft = scrollStartX + dx
    scrollRef.value.scrollTop = scrollStartY + dy
  }
}

function onMouseUp() {
  isDragging.value = false
}

watch(() => props.url, loadPdf, { immediate: true })

onBeforeUnmount(() => {
  if (pdfDoc) { pdfDoc.destroy(); pdfDoc = null }
  canvasRefs.clear()
  renderQueue.clear()
})
</script>

<template>
  <div class="pdf-viewer-root">
    <!-- Loading -->
    <div v-if="loading" class="pdf-viewer-status">
      <div class="pdf-viewer-spinner" />
      <p>正在加载 PDF...</p>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="pdf-viewer-status is-error">
      {{ error }}
    </div>

    <!-- PDF content -->
    <template v-else>
      <!-- Toolbar -->
      <div class="pdf-viewer-toolbar">
        <span class="pdf-viewer-title">{{ title || 'PDF 预览' }}</span>
        <span class="pdf-viewer-page-info">{{ pageCount }} 页</span>
        <div class="pdf-viewer-zoom">
          <button :disabled="scale <= 0.5" @click="toolbarZoom(-0.25)">
            <Minus :size="14" />
          </button>
          <span class="pdf-viewer-zoom-val">{{ Math.round(scale * 100) }}%</span>
          <button :disabled="scale >= 3" @click="toolbarZoom(0.25)">
            <Plus :size="14" />
          </button>
        </div>
      </div>

      <!-- Scrollable pages -->
      <div
        ref="scrollRef"
        class="pdf-viewer-scroll"
        :class="{ 'is-dragging': isDragging }"
        @wheel="onWheel"
        @mousedown="onMouseDown"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseUp"
      >
        <div
          v-for="cw in canvasWraps"
          :key="cw.pageNum"
          class="pdf-viewer-page"
        >
          <canvas
            :ref="(el: unknown) => getCanvasRef(el, cw.pageNum)"
          />
          <div class="pdf-viewer-page-footer">
            第 {{ cw.pageNum }} / {{ pageCount }} 页
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pdf-viewer-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.pdf-viewer-status {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 14px;
  gap: 12px;
}

.pdf-viewer-status.is-error {
  color: #ef4444;
}

.pdf-viewer-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: pdf-spin 0.7s linear infinite;
}

@keyframes pdf-spin {
  to { transform: rotate(360deg); }
}

/* ── Toolbar ── */

.pdf-viewer-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.pdf-viewer-title {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.pdf-viewer-page-info {
  font-size: 12px;
  color: #94a3b8;
}

.pdf-viewer-zoom {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pdf-viewer-zoom button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}

.pdf-viewer-zoom button:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #2563eb;
}

.pdf-viewer-zoom button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.pdf-viewer-zoom-val {
  font-size: 12px;
  color: #475569;
  min-width: 36px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* ── Scroll area ── */

.pdf-viewer-scroll {
  flex: 1;
  overflow: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #f1f5f9;
  cursor: grab;
  user-select: none;
}

.pdf-viewer-scroll.is-dragging {
  cursor: grabbing;
}

/* ── Page ── */

.pdf-viewer-page {
  flex-shrink: 0;
  margin: 0 auto;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06);
}

.pdf-viewer-page canvas {
  display: block;
}

.pdf-viewer-page-footer {
  padding: 4px 0;
  text-align: center;
  font-size: 11px;
  color: #94a3b8;
  background: #fff;
  border-top: 1px solid #f1f5f9;
}
</style>
