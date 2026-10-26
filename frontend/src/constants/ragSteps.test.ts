import { describe, it, expect } from 'vitest'
import { currentRunningStep, RAG_STEPS } from './ragSteps'
import type { RagSteps, RagStep } from '@/types'
import type { StepStatus } from '@/types/step'

/**
 * 待答提示必须反映**真实执行到的步骤**。
 *
 * 这里锁住的是一条曾经存在的行为缺陷：`AiMessage` 原先把 5 句文案每 2.2 秒
 * 随机轮换，与后端 `pending` 的那一步毫无关系 —— 用户看到「检索文献中…」
 * 时可能其实还停在意图识别。改成按 `ragSteps` 推导后，用测试守住。
 */
function step(status: StepStatus): RagStep {
  return { status, title: 't' }
}

describe('currentRunningStep', () => {
  it('没有步骤时返回 null', () => {
    expect(currentRunningStep(undefined)).toBeNull()
    expect(currentRunningStep({})).toBeNull()
  })

  it('只有意图识别 pending → intent', () => {
    const steps: RagSteps = { intent: step('pending') }
    expect(currentRunningStep(steps)).toBe('intent')
  })

  it('意图识别 done、检索 pending → retrieval', () => {
    const steps: RagSteps = { intent: step('done'), retrieval: step('pending') }
    expect(currentRunningStep(steps)).toBe('retrieval')
  })

  it('前两步 done、融合 pending → fusion', () => {
    const steps: RagSteps = {
      intent: step('done'),
      retrieval: step('done'),
      fusion: step('pending'),
    }
    expect(currentRunningStep(steps)).toBe('fusion')
  })

  it('前三步 done、回答 pending → answer', () => {
    const steps: RagSteps = {
      intent: step('done'),
      retrieval: step('done'),
      fusion: step('done'),
      answer: step('pending'),
    }
    expect(currentRunningStep(steps)).toBe('answer')
  })

  it('四步全部 done → null（应显示步骤数而非进行中文案）', () => {
    const steps: RagSteps = {
      intent: step('done'),
      retrieval: step('done'),
      fusion: step('done'),
      answer: step('done'),
    }
    expect(currentRunningStep(steps)).toBeNull()
  })

  it('skipped 也算走完（降级直通时不该卡在跳过的那步）', () => {
    const steps: RagSteps = {
      intent: step('done'),
      retrieval: step('skipped'),
      fusion: step('pending'),
    }
    expect(currentRunningStep(steps)).toBe('fusion')
  })

  it('旧数据的 completed 归一后算走完', () => {
    const steps = {
      intent: { status: 'completed', title: 't' },
      retrieval: step('pending'),
    } as unknown as RagSteps
    expect(currentRunningStep(steps)).toBe('retrieval')
  })

  it('直答分支只有 intent + answer，中间步骤缺失不影响判定', () => {
    const steps: RagSteps = { intent: step('done'), answer: step('pending') }
    expect(currentRunningStep(steps)).toBe('answer')
  })
})

describe('RAG_STEPS', () => {
  it('顺序与后端节点执行顺序一致', () => {
    expect(RAG_STEPS.map((s) => s.key)).toEqual([
      'intent',
      'retrieval',
      'fusion',
      'answer',
    ])
  })

  it('每步都有 label / sub / doing，且 doing 不带省略号（由调用方统一补）', () => {
    for (const s of RAG_STEPS) {
      expect(s.label.length).toBeGreaterThan(0)
      expect(s.sub.length).toBeGreaterThan(0)
      expect(s.doing.length).toBeGreaterThan(0)
      expect(s.doing.endsWith('…')).toBe(false)
    }
  })
})
