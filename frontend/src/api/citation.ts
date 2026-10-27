import api from './index'

/**
 * 引用定位：拿 snippet 在 PDF 里的精确位置（页码 + bbox）。
 *
 * 数据来自 MinerU 的 `content_list.json`（每条文本带 `bbox` 0-1000 归一化坐标 +
 * `page_idx`）。**这是替换 pdf.js 全文搜索的关键**：
 *
 *   旧实现：findController 在文本层里搜纯文本
 *     - 必须先加载完整份 PDF（2.76MB @ 240KB/s ≈ 12s）才可能搜到
 *     - MinerU 抽取文本与 PDF 文本层在标点/空格上不一致，稍长就 0 命中
 *   新实现：后端按 snippet 在 content_list 里匹配，返回坐标
 *     - 不依赖 PDF 是否加载完
 *     - 不受文本差异影响（后端做了标点归一化）
 */
export interface CitationBox {
  /** 页码，1-based（后端已 +1） */
  page: number
  /** [x0, y0, x1, y1]，相对页面宽高的 0-1000 归一化值 */
  bbox: [number, number, number, number]
  /** 命中条目的原始文本，用于校验 */
  text: string
}

export interface CitationLocateResponse {
  found: boolean
  boxes: CitationBox[]
  total_pages: number
  md5: string | null
  message: string
}

export async function locateCitationApi(
  docId: string,
  snippet: string,
): Promise<CitationLocateResponse> {
  const res = await api.get<CitationLocateResponse>(
    `/v1/documents/${docId}/locate`,
    { params: { snippet } },
  )
  return res.data
}

/**
 * 证据卡数据：摘要分段 + 样本量 + 连续上下文。
 *
 * 与 `/locate` 分工不同 —— 那个回答「这句话在 PDF 第几页哪个位置」（给 pdf.js
 * 画框），这个回答「这篇文献说了什么、方法是什么、上下文是什么」（给证据卡渲染）。
 *
 * `abstract_sections` 为空数组表示该文献**没有结构式摘要**（本机 1248 篇中
 * 337 篇如此，多为指南与综述）。此时前端必须回退到 `abstract_raw` 整段展示，
 * **不要伪造一段「结论」** —— 那会让用户以为文章真有结论句。
 */
export interface AbstractSection {
  /** 背景/目的/方法/结果/结论；空字符串表示无分段 */
  key: string
  text: string
}

/**
 * 抽到的样本量。**启发式结果，不是事实**，UI 上应作为提示而非权威数字。
 *
 * `is_subject_count === false` 表示抽到的是「纳入 N 篇文献」的篇数，
 * 此时不能标成「样本量」—— 那是文献数量，不是受试者数。
 */
export interface SampleSize {
  value: number
  unit: string
  is_subject_count: boolean
}

/**
 * 连续正文：上文 + 命中 + 下文。
 *
 * 刻意不拆成三块让前端拼接：读者要读的是一段连续的话，原文只是被 chunk
 * 边界切开了。前端按 prev → hit → next 顺序渲染成一段文本，命中段落单独
 * 高亮，其余褪色。
 */
export interface EvidencePassage {
  prev_heading: string
  prev_text: string
  hit_heading: string
  hit_paragraphs: string[]
  next_heading: string
  next_text: string
  has_prev: boolean
  has_next: boolean
}

export interface EvidenceResponse {
  doc_id: string
  title: string
  authors: string
  journal: string
  source: string
  year: string
  article_type: string
  doi: string
  keywords: string[]

  abstract_raw: string
  abstract_sections: AbstractSection[]
  /** 是否有「结论」段 —— 决定结论区块是摘录还是降级提示 */
  has_conclusion: boolean
  sample_size: SampleSize | null

  /** 传了 snippet 才有；为空表示未定位到命中章节 */
  passage: EvidencePassage | null
  md5: string | null
  message: string
}

export async function fetchEvidenceApi(
  docId: string,
  snippet = '',
): Promise<EvidenceResponse> {
  const res = await api.get<EvidenceResponse>(
    `/v1/documents/${docId}/evidence`,
    { params: snippet ? { snippet } : {} },
  )
  return res.data
}
