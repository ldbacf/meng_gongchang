import type { RagSteps } from '@/types'
import { isStepDone, normalizeStepStatus } from '@/types/step'

/**
 * RAG 四步的显示定义 —— 单一来源。
 *
 * 两个地方曾经各写一份，必然漂移：
 *   - `AiMessage` 待答文案轮换（随机挑 5 句，与真实步骤无关）
 *   - `RagPipelineSimple` 的步骤列表（顺序 + 中英标签）
 *
 * `label` / `sub` 用于步骤列表；`doing` 用于「正在做这件事」的单句提示。
 * 注意 `doing` 不以「…」结尾：调用方统一补省略号，避免两处风格不一。
 */
export const RAG_STEPS = [
  { key: 'intent', label: '意图识别', sub: 'Query Rewriting', doing: '正在理解问题' },
  { key: 'retrieval', label: '混合检索', sub: 'Hybrid Search', doing: '检索文献中' },
  { key: 'fusion', label: '融合重排', sub: 'Reranking', doing: '融合排序中' },
  { key: 'answer', label: '生成回答', sub: 'Answer', doing: '生成医学回答中' },
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
