import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Citation, Message } from '@/types'
import { fetchEvidenceApi, locateCitationApi } from '@/api/citation'
import type { CitationBox, EvidenceResponse } from '@/api/citation'

/**
 * 右侧文献面板的状态与打开/关闭。
 *
 * 从 ChatView.vue 抽出来（原来那里 400 多行，滚动、SSE、面板、引用全混在一起）。
 * 职责：当前看的是哪条引用、PDF 地址、**引用在原文中的精确位置**，
 * 以及**证据卡数据**（摘要分段 / 样本量 / 连续上下文）。
 *
 * 面板默认展示证据卡，PDF 是「查看原文」之后的第二层 —— 因为本机 MinIO
 * 实测 240 KB/s，整份 2.76 MB 要 11.7 秒；而证据卡随引用一次返回，毫秒级。
 *
 * **PDF 地址直接给 pdf.js**，不让 axios 先整份下载：
 * 曾走「axios 取 blob → createObjectURL」的路子，2 MB 的 PDF 在
 * 250 KB/s 的链路上要等约 8 秒才出第一页；交给 pdf.js 按 Range 分片拉，
 * 首页基本是秒开。
 *
 * **定位不再靠 pdf.js 搜全文**：改为调后端 `/locate` 拿 MinerU 的 bbox
 * （见 `api/citation.ts` 的说明）。定位请求与证据卡并行发出，
 * 谁先回来都不阻塞另一方。
 */
export function useCitationPanel(messages: Ref<Message[]> | ComputedRef<Message[]>) {
  const open = ref(false)
  /** 当前正在看的那条引用；为 null 表示在看「参考文献列表」 */
  const activeCitation = ref<Citation | null>(null)
  const pdfUrl = ref<string | null>(null)
  const pdfLoading = ref(false)
  /** 该引用在原文中的位置（来自后端 bbox 定位） */
  const highlightBoxes = ref<CitationBox[] | null>(null)
  /** 定位失败时的说明（前端展示为「未定位到原文」，但不影响阅读 PDF） */
  const locateMessage = ref('')
  /** 从引用列表点进来的，才显示返回列表按钮 */
  const showBackButton = ref(false)

  /** 证据卡数据（摘要分段 / 样本量 / 连续上下文） */
  const evidence = ref<EvidenceResponse | null>(null)
  const evidenceLoading = ref(false)
  /** 面板视图：默认证据卡，点「查看原文」才切到 PDF */
  const view = ref<'evidence' | 'pdf'>('evidence')

  /** 栅栏：快速连点不同引用时，只让最后一次请求落盘 */
  let evidenceSeq = 0

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
    highlightBoxes.value = null
    locateMessage.value = ''
  }

  function clearEvidence() {
    evidence.value = null
    evidenceLoading.value = false
  }

  /**
   * 拉证据卡数据。
   *
   * 失败**不是错误**：只意味着拿不到摘要/上下文，引用片段与 PDF 都还在。
   * 所以吞掉异常，让面板回落到「暂无详细信息」，不弹 toast 也不抛。
   *
   * 用序号栅栏防竞态：用户连点 [1] [2] [3] 时三个请求并发，返回顺序不定，
   * 不用栅栏会把 [1] 的内容渲染到 [3] 的位置上。
   */
  async function loadEvidence(citation: Citation) {
    if (!citation.doc_id) {
      clearEvidence()
      return
    }
    const seq = ++evidenceSeq
    evidenceLoading.value = true
    try {
      const res = await fetchEvidenceApi(citation.doc_id, citation.snippet ?? '')
      if (seq !== evidenceSeq) return // 已被更新的请求取代
      evidence.value = res
    } catch (e) {
      if (seq !== evidenceSeq) return
      evidence.value = null
      console.warn('load evidence failed:', e)
    } finally {
      if (seq === evidenceSeq) evidenceLoading.value = false
    }
  }

  /**
   * 定位引用在 PDF 中的位置。
   *
   * 失败**不是错误**：只意味着拿不到 bbox，PDF 仍然可读，摘录卡也还在。
   * 所以这里吞掉异常只记录 message，不向上抛。
   */
  async function locate(citation: Citation) {
    if (!citation.doc_id) return
    const snippet = (citation.snippet ?? '').trim()
    if (!snippet) return

    try {
      const res = await locateCitationApi(citation.doc_id, snippet)
      if (res.found && res.boxes.length) {
        highlightBoxes.value = res.boxes
        locateMessage.value = ''
      } else {
        highlightBoxes.value = null
        locateMessage.value = res.message || '未在解析结果中找到该片段'
      }
    } catch (e) {
      highlightBoxes.value = null
      locateMessage.value = '定位请求失败，已跳过高亮'
      console.warn('locate citation failed:', e)
    }
  }

  function openCitation(citation: Citation, fromList = false) {
    activeCitation.value = citation
    showBackButton.value = fromList
    open.value = true
    view.value = 'evidence'
    clearPdf()
    clearEvidence()

    if (citation.doc_id) {
      pdfLoading.value = false
      pdfUrl.value = `/api/v1/documents/${citation.doc_id}/pdf/stream`
      // 证据卡与 bbox 定位并行：都不 await，谁先回来都不挡另一方
      void loadEvidence(citation)
      void locate(citation)
      return
    }
    // 没有 doc_id 的引用（历史数据）只能看摘要，没有 PDF 可开
    pdfLoading.value = false
  }

  /** 面板里「查看原文 PDF」—— 从证据卡切到 PDF 视图 */
  function showPdf() {
    view.value = 'pdf'
  }

  /** 从 PDF 视图退回证据卡 */
  function showEvidence() {
    view.value = 'evidence'
  }

  function openList() {
    activeCitation.value = null
    showBackButton.value = false
    open.value = true
    view.value = 'evidence'
    clearPdf()
    clearEvidence()
  }

  function backToList() {
    activeCitation.value = null
    view.value = 'evidence'
    clearPdf()
    clearEvidence()
  }

  function close() {
    open.value = false
    activeCitation.value = null
    view.value = 'evidence'
    clearPdf()
    clearEvidence()
  }

  return {
    open,
    activeCitation,
    pdfUrl,
    pdfLoading,
    highlightBoxes,
    locateMessage,
    showBackButton,
    uniqueCitations,
    pdfHeaders,
    evidence,
    evidenceLoading,
    view,
    openCitation,
    openList,
    backToList,
    showPdf,
    showEvidence,
    close,
  }
}
