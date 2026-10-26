import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AiMessage from './AiMessage.vue'
import type { Message, RagSteps } from '@/types'
import type { StepStatus } from '@/types/step'

/**
 * 待答提示必须跟随真实步骤。
 *
 * 回归背景：`AiMessage` 的标题文案原先是从 5 句里**随机**挑一句、每 2.2 秒轮换
 * （「正在理解问题…」「检索文献中…」「分析医学资料…」…），跟后端执行到哪一步
 * 毫无关系。截图里出现过「检索文献中…」但实际还停在意图识别的情况。
 * 现在改为读 `ragSteps` 里那个 `pending` 的步骤。
 */
function step(status: StepStatus): {
  status: StepStatus
  title: string
} {
  return { status, title: 't' }
}

function makeMessage(ragSteps?: RagSteps): Message {
  return {
    id: 'm1',
    role: 'ai',
    content: '',
    timestamp: Date.now(),
    ragSteps,
  }
}

function titleText(steps: RagSteps): string {
  const wrapper = mount(AiMessage, {
    props: { message: makeMessage(steps), isStreaming: true, streamContent: '' },
    global: { stubs: { RagPipelineSimple: true } },
  })
  // 待答标题在步骤面板的按钮里，带 accent-text 样式
  return wrapper.find('.text-accent-text').text()
}

describe('AiMessage 待答提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('意图识别中 → 显示「正在理解问题…」', () => {
    expect(titleText({ intent: step('pending') })).toBe('正在理解问题…')
  })

  it('混合检索中 → 显示「检索文献中…」', () => {
    expect(
      titleText({ intent: step('done'), retrieval: step('pending') }),
    ).toBe('检索文献中…')
  })

  it('融合重排中 → 显示「融合排序中…」（不再随机跳到别的句子）', () => {
    expect(
      titleText({
        intent: step('done'),
        retrieval: step('done'),
        fusion: step('pending'),
      }),
    ).toBe('融合排序中…')
  })

  it('生成回答中 → 显示「生成医学回答中…」', () => {
    expect(
      titleText({
        intent: step('done'),
        retrieval: step('done'),
        fusion: step('done'),
        answer: step('pending'),
      }),
    ).toBe('生成医学回答中…')
  })

  it('同一份步骤反复渲染，文案稳定（不存在随机轮换）', () => {
    const steps: RagSteps = { intent: step('done'), retrieval: step('pending') }
    const seen = new Set<string>()
    for (let i = 0; i < 8; i++) seen.add(titleText(steps))
    expect([...seen]).toEqual(['检索文献中…'])
  })

  it('四步都完成后不再显示待答文案，改为「N 步」标题', () => {
    const wrapper = mount(AiMessage, {
      props: {
        message: makeMessage({
          intent: step('done'),
          retrieval: step('done'),
          fusion: step('done'),
          answer: step('done'),
        }),
        isStreaming: false,
      },
      global: { stubs: { RagPipelineSimple: true } },
    })
    expect(wrapper.find('.text-accent-text').exists()).toBe(false)
    expect(wrapper.text()).toContain('检索与推理过程')
  })
})
