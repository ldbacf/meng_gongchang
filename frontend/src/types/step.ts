/**
 * 步骤状态 —— 与后端 `app/domain/lifecycle.py` 一一对应的镜像。
 *
 * 唯一的跨端契约：合法的只有这 5 个值，`done` 是规范的成功态。
 *
 * 历史包袱：早期前端把 `done` 读成 `completed`，两套值并存导致历史会话回放时
 * 勾选态丢失、步骤点不开。现在只在**读取边界**（`normalizeStepStatus`）把旧值
 * 归一一次，其余所有地方一律比较 `done`。
 */

export type StepStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'

const CANONICAL: ReadonlySet<string> = new Set<StepStatus>([
  'pending',
  'running',
  'done',
  'failed',
  'skipped',
])

/** 仅用于读取旧数据；写入方永远不该产生这些值 */
const LEGACY_ALIASES: Record<string, StepStatus> = {
  completed: 'done',
  complete: 'done',
  success: 'done',
  error: 'failed',
}

/**
 * 把任意输入归一成合法的 `StepStatus`。
 *
 * 未知值不抛错：历史数据可能来自更早版本，宁可降级成 `pending` 让界面还能渲染，
 * 也不要因为一条脏数据让整个会话打不开。
 */
export function normalizeStepStatus(value: unknown): StepStatus {
  if (typeof value !== 'string') return 'pending'
  const v = value.trim().toLowerCase()
  if (!v) return 'pending'
  const alias = LEGACY_ALIASES[v]
  if (alias) return alias
  return CANONICAL.has(v) ? (v as StepStatus) : 'pending'
}

/** 是否已成功完成（`skipped` 也算走完，例如降级直通） */
export function isStepDone(value?: StepStatus | null): boolean {
  return value === 'done' || value === 'skipped'
}

/** 是否仍在进行 */
export function isStepRunning(value?: StepStatus | null): boolean {
  return value === 'pending' || value === 'running'
}
