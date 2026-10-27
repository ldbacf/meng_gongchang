import type { LiveProgressMetrics, RagSteps } from '@/types'
import { isStepDone, normalizeStepStatus } from '@/types/step'

/**
 * RAG 四步的显示定义 —— 单一来源。
 *
 * 两个地方曾经各写一份，必然漂移：
 *   - `AiMessage` 待答文案轮换（随机挑 5 句，与真实步骤无关）
 *   - `RagPipelineSimple` 的步骤列表（顺序 + 中英标签）
 */
export const RAG_STEPS = [
  { key: 'intent', label: '意图识别', sub: 'Query Rewriting' },
  { key: 'retrieval', label: '混合检索', sub: 'Hybrid Search' },
  { key: 'fusion', label: '融合重排', sub: 'Reranking' },
  { key: 'answer', label: '生成回答', sub: 'Answer' },
] as const

export type RagStepKey = (typeof RAG_STEPS)[number]['key']

/**
 * 推断当前正在跑哪一步。
 *
 * 后端每个节点先发 `pending` 再发 `done`，四步串行，所以任一时刻
 * **最多有一个** `pending`。按定义顺序取第一个未完成的即可。
 *
 * 返回 `null` 表示四步都已完成（或还没有任何步骤）。
 */
export function currentRunningStep(steps: RagSteps | undefined): RagStepKey | null {
  if (!steps) return null
  for (const def of RAG_STEPS) {
    const step = (steps as Record<string, { status?: unknown } | undefined>)[def.key]
    if (!step) continue
    if (!isStepDone(normalizeStepStatus(step.status))) return def.key
  }
  return null
}

// ══════════════════════════════════════════════════════════════
// 待答提示文案：按步骤类型固定分配
// ══════════════════════════════════════════════════════════════
//
// 三种表达方式混用，规则是**按步骤类型固定**，不是随机：
//   意图识别 / 生成回答  → 时间尺度（按已耗时递进换句），没有天然数字可用
//   混合检索 / 融合重排  → 实时计数优先，拿不到数字就退化为时间尺度
//
// 逐字出现是**所有**提示的统一渲染方式（在 AiMessage 里做），不属于某一类。
//
// 为什么这两步能显示计数：后端 retrieval 在 embed / milvus / 每批 es 各发一帧
// `live: true` 的进度（真实值，ES 分批翻页 + 两路并行），fusion 在 rrf 之后和
// rerank 之后各发一帧。其余两步没有可分段上报的天然节点，硬编数字就是造假。

/** 文案片段：`{n}` 会被替换成当前计数徽标 */
export interface PhraseVariant {
  /** 该步骤已耗时达到多少毫秒后启用这句 */
  at: number
  /** 文案模板；含 `{n}` 时必须有计数可用，否则退化为 `fallback` */
  text: string
}

interface StepCopy {
  /** 有计数时用这一组 */
  withCount?: PhraseVariant[]
  /** 无计数（或计数为 0）时用这一组 —— 不显示「0 篇」这种丧气话 */
  fallback: PhraseVariant[]
}

// ══════════════════════════════════════════════════════════════
// 时间档位：1s / 5s / 15s / 30s
// ══════════════════════════════════════════════════════════════
//
// 为什么是这个尺度：
// 实测四步耗时可达 intent 7.7s → retrieval 28.8s → fusion 6.8s → answer 14s。
// 原档位只覆盖 0–2.6s，任何超过 2.6 秒的步骤都**永远停在最后一句**，
// 用户盯着「两路结果汇合，累计 400 条…」27 秒不动，看起来就是卡死。
//
// 现在按对数尺度递增（1 → 5 → 15 → 30），越往后文案越具体、越有"仍在推进"的
// 信息量；30s 之后不再换句（再换就是噪音），此时用户已在看下面的实时耗时与计数。
//
// 阈值刻意对齐「人开始怀疑卡死」的时间点：
//   1s  —— 刚起步，只说在做什么
//   5s  —— 开始觉得有点久，给一句更具体的过程描述
//   15s —— 明显偏久，明确告诉用户慢在哪、不是卡住
//   30s —— 很慢了，给出可预期的话术（文献多时更久是正常的）
const T_QUICK = 1000
const T_MID = 5000
const T_SLOW = 15000
const T_VERY_SLOW = 30000

const COPY: Record<RagStepKey, StepCopy> = {
  intent: {
    // 意图识别没有"数量"语义，只用时间尺度
    fallback: [
      { at: 0, text: '正在理解问题…' },
      { at: T_QUICK, text: '正在补全医学上下文…' },
      { at: T_MID, text: '正在识别问题类型与关键信息…' },
      { at: T_SLOW, text: '正在判断这个问题该查库还是直接作答…' },
      { at: T_VERY_SLOW, text: '意图判定比平时慢，模型在生成改写后的检索式…' },
    ],
  },
  retrieval: {
    withCount: [
      { at: 0, text: '正在并行检索向量库与关键词索引…' },
      // 措辞用「条」：这是 chunk 数（两路原始命中，有重叠），不是「篇」文献
      { at: T_QUICK, text: '已召回 {n} 条候选…' },
      { at: T_MID, text: '两路结果汇合，累计 {n} 条…' },
      { at: T_SLOW, text: '已取回 {n} 条，正在按语义去重…' },
      { at: T_VERY_SLOW, text: '知识库较大，已检索 {n} 条，仍在补充召回…' },
    ],
    fallback: [
      { at: 0, text: '正在并行检索向量库与关键词索引…' },
      { at: T_QUICK, text: '两路结果正在汇合…' },
      { at: T_MID, text: '正在按语义相似度去重…' },
      { at: T_SLOW, text: '检索耗时偏长，正在确认两路结果是否完整…' },
      { at: T_VERY_SLOW, text: '知识库较大，检索仍在进行，请稍候…' },
    ],
  },
  fusion: {
    withCount: [
      { at: 0, text: '正在用重排模型给候选打分…' },
      { at: T_QUICK, text: '比对 {n} 篇候选…' },
      { at: T_MID, text: '比对 {n} 篇，正在精选最相关段落…' },
      { at: T_SLOW, text: '重排 {n} 篇耗时偏长，模型在逐条精算…' },
      { at: T_VERY_SLOW, text: '候选较多（{n} 篇），重排仍在进行…' },
    ],
    fallback: [
      { at: 0, text: '正在用重排模型给候选打分…' },
      { at: T_QUICK, text: '重排模型逐条打分中…' },
      { at: T_MID, text: '正在裁掉不相关段落…' },
      { at: T_SLOW, text: '重排耗时偏长，模型在深度比对候选段落…' },
      { at: T_VERY_SLOW, text: '候选较多，重排仍在进行，请稍候…' },
    ],
  },
  answer: {
    fallback: [
      { at: 0, text: '正在组织证据与结论…' },
      { at: T_QUICK, text: '正在核对引用的原文出处…' },
      { at: T_MID, text: '正在逐句确认每个结论都有出处…' },
      { at: T_SLOW, text: '回答较长，正在收尾并复核引用编号…' },
      { at: T_VERY_SLOW, text: '生成时间偏长，长回答会更久，正在继续输出…' },
    ],
  },
}

/** 把 `"已召回 {n} 篇"` 拆成 `['已召回 ', ' 篇']`，供模板或逐字渲染插入计数徽标 */
export function splitCountTemplate(text: string): string[] {
  return text.split('{n}')
}

/**
 * 从步骤的 live 进度里取出该步的计数。
 *
 * - retrieval：读 `fetched`（两路已取回的**原始条数**）。措辞必须用「条」而不是
 *   「篇」——这是 chunk 数，一篇文献可能贡献多条，且两路有重叠。
 *   早年想用 `milvus + es` 直接拼成「已召回 N 篇」，实测显示 400 而真实去重只有 372，
 *   既虚高又量纲不对。
 * - fusion：`input_count`（候选）/ `output_count`（精选），优先展示前者，
 *   精选数出现后由调用方决定是否切换。
 *
 * 返回 `null` 表示**当前不可用**（这是常态，pending 首帧就没有数字）。
 */
export function liveCountOf(
  key: RagStepKey,
  metrics: LiveProgressMetrics | undefined,
): { value: number; kind: 'retrieval' | 'fusion' } | null {
  if (!metrics?.live) return null

  if (key === 'retrieval') {
    // 优先 fetched（原始条数）；没有就退回两路之和
    const v = metrics.fetched ?? (metrics.milvus_hits ?? 0) + (metrics.es_hits ?? 0)
    return v > 0 ? { value: v, kind: 'retrieval' } : null
  }
  if (key === 'fusion') {
    // 有精选数就用精选数（"精选 5 段"比"比对 12 篇"更接近完成态）
    const out = metrics.output_count ?? 0
    if (out > 0) return { value: out, kind: 'fusion' }
    const inp = metrics.input_count ?? 0
    return inp > 0 ? { value: inp, kind: 'fusion' } : null
  }
  return null
}

export interface StepHint {
  /** 纯文本模板（可能含 `{n}`，配合 `count` 使用） */
  text: string
  /** 有计数时的数字；`null` 表示该句不含计数 */
  count: number | null
  /** 用于判断「文案是否变了」——含计数，避免数字更新时不重绘 */
  signature: string
}

/**
 * 计算某一步当前该显示什么。
 *
 * @param key      步骤
 * @param elapsed  该步骤已耗时（毫秒）
 * @param metrics  该步骤最新的 metrics（可能是 live 进度，也可能是完成态）
 */
export function stepHint(
  key: RagStepKey,
  elapsed: number,
  metrics?: LiveProgressMetrics | Record<string, unknown>,
): StepHint {
  const copy = COPY[key]
  const live = liveCountOf(key, metrics as LiveProgressMetrics | undefined)

  // 有计数 → 优先用 withCount 组里**带 {n} 的第一句**
  //
  // 注意不能直接用 pickByElapsed 的结果：withCount[0] 那句（at: 0）故意是不带数字的
  // 过渡句（「正在并行检索…」），本意是「还没数字时先垫一句」。但如果数字已经拿到了，
  // 再显示过渡句就等于**把已得的计数藏起来** —— 实测就是这样：mv=200 es=200 时
  // 界面仍停在「正在并行检索向量库与关键词索引…」，数字徽标一个都没出现。
  // 正确做法：有数字就从「第一句含 {n} 的文案」开始按耗时取，跳过前置过渡句。
  if (live && copy.withCount) {
    const counted = copy.withCount.filter((v) => v.text.includes('{n}'))
    const pool = counted.length ? counted : copy.withCount
    const variant = pickByElapsed(pool, elapsed)

    if (variant.text.includes('{n}')) {
      return {
        text: variant.text,
        count: live.value,
        signature: `${variant.text}|${live.value}`,
      }
    }
    return { text: variant.text, count: null, signature: variant.text }
  }

  // 无计数 → fallback（文案里不带 {n}）
  const variant = pickByElapsed(copy.fallback, elapsed)
  return { text: variant.text, count: null, signature: variant.text }
}

function pickByElapsed(variants: PhraseVariant[], elapsed: number): PhraseVariant {
  let chosen = variants[0]
  for (const v of variants) {
    if (elapsed >= v.at) chosen = v
  }
  return chosen
}
