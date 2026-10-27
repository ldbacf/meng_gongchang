import { describe, it, expect } from 'vitest'
import { currentRunningStep, RAG_STEPS, splitCountTemplate, stepHint } from './ragSteps'
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

  it('每步都有 label / sub', () => {
    for (const s of RAG_STEPS) {
      expect(s.label.length).toBeGreaterThan(0)
      expect(s.sub.length).toBeGreaterThan(0)
    }
  })
})

// ══════════════════════════════════════════════════════════════
// 待答文案：按步骤类型固定分配（计数 / 时间尺度）
// ══════════════════════════════════════════════════════════════

describe('stepHint — 计数与退化的分配规则', () => {
  it('意图识别：只用时间尺度，永远不带计数', () => {
    const a = stepHint('intent', 0, { live: true, milvus_hits: 99 })
    expect(a.count).toBeNull()
    expect(a.text).toBe('正在理解问题…')

    const b = stepHint('intent', 2000, { live: true })
    expect(b.count).toBeNull()
    expect(b.text).toBe('正在补全医学上下文…')
  })

  it('生成回答：只用时间尺度，永远不带计数', () => {
    expect(stepHint('answer', 0, { live: true }).count).toBeNull()
    // 档位是 1s/5s/15s/30s：15s 时应进入「回答较长…」那档
    expect(stepHint('answer', 16000, { live: true }).text).toBe(
      '回答较长，正在收尾并复核引用编号…',
    )
  })

  it('混合检索：拿到数字就显示计数', () => {
    const h = stepHint('retrieval', 1500, { live: true, fetched: 12 })
    expect(h.count).toBe(12)
    expect(h.text).toContain('{n}')
  })

  it('混合检索：没有数字时退化为过程描述（不显示「0 条」）', () => {
    const noLive = stepHint('retrieval', 1500, undefined)
    expect(noLive.count).toBeNull()
    expect(noLive.text).toBe('两路结果正在汇合…')
    expect(noLive.text).not.toContain('0')

    // 计数为 0 时同样退化
    const zero = stepHint('retrieval', 1500, { live: true, fetched: 0 })
    expect(zero.count).toBeNull()
    expect(zero.text).toBe('两路结果正在汇合…')
  })

  it('融合重排：优先用精选数，没有则用候选数', () => {
    const onlyInput = stepHint('fusion', 1500, { live: true, input_count: 12 })
    expect(onlyInput.count).toBe(12)

    const withOutput = stepHint('fusion', 1500, {
      live: true,
      input_count: 12,
      output_count: 5,
    })
    expect(withOutput.count).toBe(5)
  })

  it('融合重排：没有数字时退化', () => {
    const h = stepHint('fusion', 1500, { live: true })
    expect(h.count).toBeNull()
    expect(h.text).toBe('重排模型逐条打分中…')
  })

  it('同一步内随耗时换句（时间尺度）', () => {
    expect(stepHint('retrieval', 0, undefined).text).toBe('正在并行检索向量库与关键词索引…')
    // 5s 档
    expect(stepHint('retrieval', 6000, undefined).text).toBe('正在按语义相似度去重…')
  })

  it('长任务不会卡在同一句：四档文案互不相同', () => {
    // 这是本轮修的核心问题：原来档位只到 2.6s，30s 的任务会一直停在最后一句
    const at = [0, 2000, 8000, 20000, 35000]
    const seen = at.map((ms) => stepHint('retrieval', ms, undefined).text)
    // 相邻档位必须变化（直到最后一档 saturation）
    expect(new Set(seen).size).toBeGreaterThanOrEqual(4)
    // 最末两档允许相同（30s 后不再换句），但 20s 与 8s 必须不同
    expect(seen[2]).not.toBe(seen[3])
  })

  it('30s 之后文案稳定（不再换句，避免噪音）', () => {
    const a = stepHint('retrieval', 30000, undefined).text
    const b = stepHint('retrieval', 90000, undefined).text
    expect(a).toBe(b)
  })

  it('数字变化会改变 signature（触发重绘），文案不变则不会', () => {
    const a = stepHint('retrieval', 900, { live: true, fetched: 12 })
    const b = stepHint('retrieval', 950, { live: true, fetched: 12 })
    const c = stepHint('retrieval', 950, { live: true, fetched: 200 })
    expect(a.signature).toBe(b.signature)
    expect(a.signature).not.toBe(c.signature)
  })
})

describe('splitCountTemplate', () => {
  it('把 {n} 拆成前后两段', () => {
    expect(splitCountTemplate('已召回 {n} 条候选…')).toEqual(['已召回 ', ' 条候选…'])
  })

  it('无占位符时返回单段', () => {
    expect(splitCountTemplate('正在理解问题…')).toEqual(['正在理解问题…'])
  })
})
