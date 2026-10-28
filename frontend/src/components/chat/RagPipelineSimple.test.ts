import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RagPipelineSimple from './RagPipelineSimple.vue'
import type { RagSteps } from '@/types'

/**
 * 步骤面板的**降级提示**。
 *
 * 真实事故：Milvus 字段名写错导致向量路恒 0 条，最终回答「知识库中未找到
 * 相关文献」。用户以为是"这个库确实没有"，真相是检索链路坏了 ——
 * 两者在界面上原本完全相同，只有 `degraded: true` 这个内部字段在数据里，
 * 界面上毫无体现。
 *
 * 现在后端把 `degraded_reason` 放进 metrics，前端必须：
 *   1. 折叠状态下也能看到「降级」标记（否则用户根本不会展开）
 *   2. 展开后给出具体原因
 *   3. **不要**把 degraded / degraded_reason 当普通指标行平铺
 */

function steps(over: Record<string, unknown> = {}): RagSteps {
  return {
    intent: { status: 'done', title: '意图识别', elapsed_ms: 1200, metrics: { coverage: 'high' } },
    retrieval: {
      status: 'done',
      title: '混合检索',
      elapsed_ms: 800,
      metrics: { milvus_hits: 0, es_hits: 12, after_dedup: 12, routing: 'es_only', degraded: false },
    },
    ...over,
  } as unknown as RagSteps
}

const degradedRetrieval = {
  status: 'done',
  title: '混合检索',
  elapsed_ms: 800,
  metrics: {
    milvus_hits: 0,
    es_hits: 12,
    after_dedup: 12,
    routing: 'es_only',
    degraded: true,
    degraded_reason: 'MilvusException: field title not exist',
  },
}

describe('RagPipelineSimple · 降级提示', () => {
  it('正常运行时不出现任何降级标记', () => {
    const w = mount(RagPipelineSimple, { props: { steps: steps() } })
    expect(w.text()).not.toContain('降级')
  })

  it('折叠状态下就能看到「降级」标记', () => {
    // 关键点：如果只在展开后才显示，用户根本不会去展开，等于没提示
    const w = mount(RagPipelineSimple, {
      props: { steps: steps({ retrieval: degradedRetrieval }) },
    })
    expect(w.text()).toContain('降级')
  })

  it('展开后显示具体原因（异常类名 + 消息）', async () => {
    const w = mount(RagPipelineSimple, {
      props: { steps: steps({ retrieval: degradedRetrieval }) },
    })

    // 点开该步
    const row = w.findAll('button').find((b) => b.text().includes('混合检索'))
    expect(row).toBeTruthy()
    await row!.trigger('click')

    expect(w.text()).toContain('该步骤降级')
    expect(w.text()).toContain('field title not exist')
  })

  it('degraded / degraded_reason 不混进指标明细行', async () => {
    const w = mount(RagPipelineSimple, {
      props: { steps: steps({ retrieval: degradedRetrieval }) },
    })

    const row = w.findAll('button').find((b) => b.text().includes('混合检索'))
    await row!.trigger('click')

    // 指标网格里应只有业务字段；这两个走专门的警示条
    expect(w.text()).not.toContain('Degraded Reason')
    expect(w.text()).not.toContain('Degraded')
    expect(w.findAll('.metric-row').map((n) => n.text()).join(' ')).not.toContain(
      'field title not exist',
    )
  })

  it('缺 degraded_reason 时给出兜底说明，而不是空白', async () => {
    const noReason = {
      status: 'done',
      title: '混合检索',
      elapsed_ms: 800,
      metrics: { milvus_hits: 0, es_hits: 0, after_dedup: 0, routing: 'none', degraded: true },
    }
    const w = mount(RagPipelineSimple, { props: { steps: steps({ retrieval: noReason }) } })

    const row = w.findAll('button').find((b) => b.text().includes('混合检索'))
    await row!.trigger('click')

    expect(w.text()).toContain('该步骤降级')
    expect(w.text()).toContain('未正常完成')
  })
})
