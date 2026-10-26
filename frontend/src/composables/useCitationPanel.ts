import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Citation, Message } from '@/types'

/**
 * 右侧文献面板的状态与打开/关闭。
 *
 * 从 ChatView.vue 抽出来（原来那里 400 多行，滚动、SSE、面板、引用全混在一起）。
 * 职责只有三件：当前看的是哪条引用、PDF 地址给谁、面板开没开。
 *
 * **PDF 地址直接给 pdf.js**，不让 axios 先整份下载：
 * 曾走「axios 取 blob → createObjectURL」的路子，2 MB 的 PDF 在
 * 250 KB/s 的链路上要等约 8 秒才出第一页；交给 pdf.js 按 Range 分片拉，
 * 首页基本是秒开。
 */
export function useCitationPanel(messages: Ref<Message[]> | ComputedRef<Message[]>) {
  const open = ref(false)
  /** 当前正在看的那条引用；为 null 表示在看「参考文献列表」 */
  const activeCitation = ref<Citation | null>(null)
  const pdfUrl = ref<string | null>(null)
  const pdfLoading = ref(false)
  /** 从引用列表点进来的，才显示返回列表按钮 */
  const showBackButton = ref(false)

  /**
   * 全部消息里的引用去重。
   *
   * key 必须含消息 id：`cite.id` 是「该条回答内的序号」("1".."5")，跨消息会重复。
   * 只用 id 做 key 会让多轮会话里第 2/3 轮的引用被第 1 轮的同号引用顶掉 ——
   * 这正是「点 [2] 打开的是上一轮文献」那个 bug 的根因。
   */
  const uniqueCitations = computed<Citation[]>(() => {
    const map = new Map<string, Citation>()
    for (const msg of messages.value) {
      for (const cite of msg.citations ?? []) {
        const key = `${msg.id}:${cite.id}`
        if (!map.has(key)) map.set(key, cite)
      }
    }
    return Array.from(map.values())
  })

  /** pdf.js 走 Range 请求时的附加头（接口需 Bearer 鉴权） */
  const pdfHeaders = computed<Record<string, string>>(() => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  })

  function clearPdf() {
    pdfUrl.value = null
  }

  function openCitation(citation: Citation, fromList = false) {
    activeCitation.value = citation
    showBackButton.value = fromList
    open.value = true
    clearPdf()

    if (citation.doc_id) {
      pdfLoading.value = false
      pdfUrl.value = `/api/v1/documents/${citation.doc_id}/pdf/stream`
      return
    }
    // 没有 doc_id 的引用（历史数据）只能看摘要，没有 PDF 可开
    pdfLoading.value = false
  }

  function openList() {
    activeCitation.value = null
    showBackButton.value = false
    open.value = true
    clearPdf()
  }

  function backToList() {
    activeCitation.value = null
    clearPdf()
  }

  function close() {
    open.value = false
    activeCitation.value = null
    clearPdf()
  }

  return {
    open,
    activeCitation,
    pdfUrl,
    pdfLoading,
    showBackButton,
    uniqueCitations,
    pdfHeaders,
    openCitation,
    openList,
    backToList,
    close,
  }
}
