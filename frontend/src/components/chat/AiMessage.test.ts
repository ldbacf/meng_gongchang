import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AiMessage from './AiMessage.vue'
import type { Message, RagSteps } from '@/types'
import type { StepStatus } from '@/types/step'

/**
 * 待答提示：步骤准确 + 按类型分配表达方式。
 *
 * 历史：这里曾是 5 句文案每 2.2s **随机**轮换，与后端执行到哪一步无关
 * （截图里出现过「检索文献中…」但实际停在意图识别）。
 *
 * 现在的规则：
 *   - 步骤取 `ragSteps` 里 pending 的那一步
 *   - 意图识别 / 生成回答 → 时间尺度（按耗时递进）
 *   - 混合检索 / 融合重排 → 真实计数优先，无数字则退化为时间尺度
 *   - 文字一律逐字出现
 */
function step(status: StepStatus): { status: StepStatus; title: string } {
  return { status, title: 't' }
}

function makeMessage(ragSteps?: RagSteps): Message {
  return { id: 'm1', role: 'ai', content: '', timestamp: Date.now(), ragSteps }
}

function mountMsg(steps: RagSteps, streaming = true) {
  return mount(AiMessage, {
    props: { message: makeMessage(steps), isStreaming: streaming, streamContent: '' },
    global: { stubs: { RagPipelineSimple: true } },
  })
}

/** 取待答提示的纯文本（逐字被拆成多个 span） */
function hintText(wrapper: ReturnType<typeof mountMsg>): string {
  const el = wrapper.find('.hint-text')
  return el.exists() ? el.text() : ''
}

describe('AiMessage 待答提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('意图识别中 → 时间尺度首句', async () => {
    const w = mountMsg({ intent: step('pending') })
    await w.vm.$nextTick()
    expect(hintText(w)).toBe('正在理解问题…')
  })

  it('混合检索中（无计数）→ 过程描述而不是「0 篇」', async () => {
    const w = mountMsg({ intent: step('done'), retrieval: step('pending') })
    await w.vm.$nextTick()
    const t = hintText(w)
    expect(t).toBe('正在并行检索向量库与关键词索引…')
    expect(t).not.toMatch(/0\s*篇/)
  })

  it('混合检索中（有计数）→ 显示数字徽标', async () => {
    const w = mountMsg({
      intent: step('done'),
      retrieval: {
        status: 'pending',
        title: 't',
        metrics: { live: true, stage: 'es', fetched: 12 },
      } as never,
    })
    // 推进到 700ms 以上，进入「已召回 {n} 篇」那句
    vi.advanceTimersByTime(900)
    await w.vm.$nextTick()

    expect(hintText(w)).toContain('12')
    // 数字用独立徽标，不是普通文字
    expect(w.find('.hint-count').exists()).toBe(true)
  })

  it('融合重排中（有计数）→ 显示精选数', async () => {
    const w = mountMsg({
      intent: step('done'),
      retrieval: step('done'),
      fusion: {
        status: 'pending',
        title: 't',
        metrics: { live: true, input_count: 12, output_count: 5 },
      } as never,
    })
    vi.advanceTimersByTime(900)
    await w.vm.$nextTick()
    expect(hintText(w)).toContain('5')
  })

  it('同一份步骤反复渲染，文案稳定（不存在随机轮换）', async () => {
    const steps: RagSteps = { intent: step('done'), retrieval: step('pending') }
    const seen = new Set<string>()
    for (let i = 0; i < 8; i++) {
      seen.add(hintText(mountMsg(steps)))
    }
    expect([...seen]).toEqual(['正在并行检索向量库与关键词索引…'])
  })

  it('四步都完成后不再显示待答提示，改为「N 步」标题', async () => {
    const w = mountMsg(
      {
        intent: step('done'),
        retrieval: step('done'),
        fusion: step('done'),
        answer: step('done'),
      },
      false,
    )
    await w.vm.$nextTick()
    expect(w.find('.hint-text').exists()).toBe(false)
    expect(w.text()).toContain('检索与推理过程')
  })

  it('逐字渲染：文案被拆成多个 char-in span', async () => {
    const w = mountMsg({ intent: step('pending') })
    await w.vm.$nextTick()
    const chars = w.findAll('.char-in')
    expect(chars.length).toBeGreaterThan(5)
  })
})
