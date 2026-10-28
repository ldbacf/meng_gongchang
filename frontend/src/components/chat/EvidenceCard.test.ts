import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EvidenceCard from './EvidenceCard.vue'
import type { EvidenceResponse } from '@/api/citation'

/**
 * 证据卡组件测试。
 *
 * 三组关注点：
 *
 * 1. **缺数据时的行为** —— 这些分支在真实语料里各占一部分（指南无结论段、
 *    Meta 只有篇数没有例数、综述什么都没有）。退化成「显示 0」或
 *    「编一段结论」会让用户被误导，比渲染不出来严重得多。
 *
 * 2. **不把实现细节印给读者** —— 初版曾在界面上显示 `doc-meta · abstract_cn`、
 *    `ES chunks · L1`、`doc_id=` 这类内部术语，还为了塞进窄栏把正文字号
 *    压到 12.5–13px。下面有一组测试专门锁住「这些不许再出现」。
 *
 * 3. **阅读动线** —— 用户点引用是来看「这句引用出自哪里」，被引原文必须
 *    排在最前；上下文默认收起，否则一屏连续文字里分不清哪句是被引的。
 */

function makeEvidence(over: Partial<EvidenceResponse> = {}): EvidenceResponse {
  return {
    doc_id: '7611',
    title: '社区H型高血压患者药物基因作用靶点多态性分布及叶酸联合维生素D干预效果研究',
    authors: '庞爱梅, 高伟, 张恒',
    journal: '中国全科医学',
    source: '2024, Vol.27, No.06',
    year: '2024',
    article_type: '论著',
    doi: '10.12114/j.issn.1007-9572.2023.0457',
    keywords: ['高血压', '基因多态性'],
    abstract_raw: '摘要： 背景 ……',
    abstract_sections: [
      { key: '背景', text: 'H型高血压严重影响着人们的健康及生活质量。' },
      { key: '方法', text: '随机抽取 200 例血压控制不佳的高血压患者。' },
      { key: '结论', text: '个体化用药效果显著；叶酸联合维生素D协同治疗更能显著降低H型高血压水平。' },
    ],
    has_conclusion: true,
    sample_size: { value: 200, unit: '例', is_subject_count: true },
    passage: {
      prev_heading: '2 结果 → 2.3 基因位点表达分析',
      prev_text: '与药物作用靶点敏感性基因多态性位点相关的是 ADRB1、ACEI。',
      hit_heading: '2 结果 → 2.4 用药对血压的影响',
      hit_paragraphs: ['A6986G:CYP3A5*1/*1（AA）患者 M3、M6 舒张压低于 M0。'],
      next_heading: '2 结果 → 2.5 两组干预前后比较',
      next_text: 'M3、M6 基因导向组 Hcy 水平低于基因组。',
      has_prev: true,
      has_next: true,
    },
    md5: '2ce5cd27ae33c0d8e4dc30962426cc54',
    message: '',
    ...over,
  }
}

const baseProps = { loading: false }

describe('EvidenceCard · 渲染', () => {
  it('渲染文献的核心字段', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.text()).toContain('社区H型高血压患者')
    expect(w.text()).toContain('中国全科医学')
    expect(w.text()).toContain('2024')
    expect(w.text()).toContain('样本量 200 例')
  })

  it('有结论段时直接展示结论', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.text()).toContain('个体化用药效果显著')
  })

  it('加载态与空态', () => {
    const loading = mount(EvidenceCard, {
      props: { loading: true, pdfAvailable: true, evidence: null },
    })
    expect(loading.text()).toContain('加载文献信息')

    const empty = mount(EvidenceCard, {
      props: { loading: false, pdfAvailable: false, evidence: null },
    })
    expect(empty.text()).toContain('暂无该文献的详细信息')
  })
})

describe('EvidenceCard · 阅读动线', () => {
  it('被引原文排在最前，出处与摘要排在它后面', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })
    const text = w.text()

    const iHit = text.indexOf('舒张压低于 M0')
    const iTitle = text.indexOf('社区H型高血压患者')
    const iAbs = text.indexOf('H型高血压严重影响着')

    expect(iHit).toBeGreaterThanOrEqual(0)
    expect(iHit).toBeLessThan(iTitle)
    expect(iTitle).toBeLessThan(iAbs)
  })

  it('命中段单独成块并标注章节路径', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.find('.ev-hit-group').text()).toContain('舒张压低于 M0')
    expect(w.find('.ev-locate').text()).toContain('2.4 用药对血压的影响')
  })

  it('上下文默认收起，点「显示上下文」才出现前后块', async () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    // 收起的形态下，前后文一个字都不该占屏
    expect(w.find('.ev-ctx').exists()).toBe(false)
    expect(w.text()).not.toContain('ADRB1')

    const btn = w.find('.ev-more')
    expect(btn.text()).toBe('显示上下文')
    await btn.trigger('click')

    const ctx = w.find('.ev-ctx')
    expect(ctx.exists()).toBe(true)
    const labels = w.findAll('.ev-ctx-label').map((n) => n.text())
    expect(labels).toEqual(['上文 · 2.3 基因位点表达分析', '下文 · 2.5 两组干预前后比较'])
    expect(ctx.text()).toContain('ADRB1')
    expect(btn.text()).toBe('收起上下文')
  })

  it('没有前后块时不出现「显示上下文」', () => {
    const ev = makeEvidence({
      passage: {
        prev_heading: '',
        prev_text: '',
        hit_heading: '2 结果',
        hit_paragraphs: ['仅有命中段。'],
        next_heading: '',
        next_text: '',
        has_prev: false,
        has_next: false,
      },
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.find('.ev-more').exists()).toBe(false)
    expect(w.find('.ev-hit-group').text()).toContain('仅有命中段')
  })

  it('上下文与命中块同节时只标「上文」，不重复整条章节名', async () => {
    const ev = makeEvidence({
      passage: {
        prev_heading: '2 结果',
        prev_text: '前一段。',
        hit_heading: '2 结果',
        hit_paragraphs: ['命中段。'],
        next_heading: '2 结果',
        next_text: '后一段。',
        has_prev: true,
        has_next: true,
      },
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })
    await w.find('.ev-more').trigger('click')

    expect(w.findAll('.ev-ctx-label').map((n) => n.text())).toEqual(['上文', '下文'])
  })
})

describe('EvidenceCard · 缺数据时降级', () => {
  it('没有结论段时整块不渲染「核心结论」，不拿正文首句冒充', () => {
    const ev = makeEvidence({ abstract_sections: [], has_conclusion: false })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.find('.ev-quote').exists()).toBe(false)
    expect(w.text()).not.toContain('核心结论')
    // 正文只出现一次（在被引原文里），不能既当结论又当原文
    expect(w.text().match(/舒张压低于 M0/g)).toHaveLength(1)
    // 也不能把内部统计口径写给读者
    expect(w.text()).not.toContain('1248')
    expect(w.text()).not.toContain('337')
  })

  it('「纳入 18 篇」标成纳入文献数，不标成样本量', () => {
    const ev = makeEvidence({ sample_size: { value: 18, unit: '篇', is_subject_count: false } })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).toContain('纳入 18 篇')
    expect(w.text()).not.toContain('样本量 18')
  })

  it('没有样本量时不渲染该标签（不显示 0）', () => {
    const w = mount(EvidenceCard, {
      props: { ...baseProps, evidence: makeEvidence({ sample_size: null }) },
    })
    expect(w.text()).not.toContain('样本量')
  })

  it('没有 passage 时给出提示，不渲染原文区', () => {
    const ev = makeEvidence({ passage: null, message: '未在解析结果中找到该片段' })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.find('.ev-hit-group').exists()).toBe(false)
    expect(w.text()).toContain('未在解析结果中找到该片段')
  })

  it('无结构式摘要时整段展示 abstract_raw', () => {
    const ev = makeEvidence({
      abstract_sections: [],
      has_conclusion: false,
      abstract_raw: '高海拔地区低压、低氧环境致人体内代谢水平发生一系列变化……',
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).toContain('高海拔地区低压、低氧环境')
  })

  it('无结构式摘要时也能折叠（否则指南/综述的整段摘要会撑满整屏）', async () => {
    const ev = makeEvidence({
      abstract_sections: [],
      has_conclusion: false,
      abstract_raw: '高血压、2型糖尿病、血脂异常被统称为「三高」……'.repeat(6),
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.find('.ev-abstract').classes()).toContain('is-clamped')

    const toggle = w.findAll('.ev-toggle').find((b) => b.text() === '展开')
    expect(toggle).toBeTruthy()
    await toggle!.trigger('click')

    expect(w.find('.ev-abstract').classes()).not.toContain('is-clamped')
  })
})

describe('EvidenceCard · 长节折叠', () => {
  /** 8285 的 2.13 一节被 chunk 合并了 5 个子节，共 11 段 */
  const longParas = Array.from({ length: 11 }, (_, i) => `第 ${i + 1} 段正文内容，用于验证折叠边界。`)

  function longEvidence(): EvidenceResponse {
    return makeEvidence({
      passage: {
        prev_heading: '',
        prev_text: '',
        hit_heading: '2 认识高血压 → 2.13 药物治疗原则',
        hit_paragraphs: longParas,
        next_heading: '',
        next_text: '',
        has_prev: false,
        has_next: false,
      },
    })
  }

  it('整节 11 段时只铺开被引的几段，其余折进「展开本节其余 N 段」', () => {
    const w = mount(EvidenceCard, {
      props: { ...baseProps, evidence: longEvidence(), snippet: longParas[0] },
    })

    // snippet 只覆盖第一段 → 只铺第一段，其余 10 段折起来
    const shown = w.findAll('.ev-hit-group .ev-para')
    expect(shown).toHaveLength(1)
    expect(shown[0].text()).toContain('第 1 段')
    expect(w.find('.ev-rest').exists()).toBe(false)

    const more = w.findAll('.ev-more').find((b) => b.text().includes('本节其余'))
    expect(more).toBeTruthy()
    expect(more!.text()).toBe('展开本节其余 10 段')
  })

  it('snippet 跨两段时铺开两段（边界由片段长度决定，不是写死 1 段）', () => {
    const w = mount(EvidenceCard, {
      props: {
        ...baseProps,
        evidence: longEvidence(),
        snippet: longParas[0] + longParas[1],
      },
    })

    expect(w.findAll('.ev-hit-group .ev-para')).toHaveLength(2)
    expect(w.findAll('.ev-more').find((b) => b.text().includes('本节其余'))!.text()).toBe(
      '展开本节其余 9 段',
    )
  })

  it('点开后才铺出其余段落', async () => {
    const w = mount(EvidenceCard, {
      props: { ...baseProps, evidence: longEvidence(), snippet: longParas[0] },
    })

    await w.findAll('.ev-more').find((b) => b.text().includes('本节其余'))!.trigger('click')

    expect(w.findAll('.ev-hit-group .ev-para')).toHaveLength(11)
    expect(w.findAll('.ev-more').find((b) => b.text().includes('本节其余'))!.text()).toBe(
      '收起本节其余内容',
    )
  })

  it('短块（≤3 段）不出现折叠按钮', () => {
    const w = mount(EvidenceCard, {
      props: { ...baseProps, evidence: makeEvidence(), snippet: '舒张压低于 M0' },
    })
    expect(w.findAll('.ev-more').find((b) => b.text().includes('本节其余'))).toBeUndefined()
  })
})

describe('EvidenceCard · 不向读者暴露实现细节', () => {
  const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })
  const text = w.text()

  it('不显示数据来源（桶名 / 字段名 / chunk 层级）', () => {
    expect(text).not.toContain('doc-meta')
    expect(text).not.toContain('abstract_cn')
    expect(text).not.toContain('ES chunks')
  })

  it('不显示内部结构说明（上文 + 命中块 + 下文）', () => {
    expect(text).not.toContain('命中块')
    expect(text).not.toContain('上文 + 命中')
  })

  it('不显示 doc_id', () => {
    expect(text).not.toContain('doc_id')
    expect(text).not.toContain('7611')
  })

  it('不显示证据等级（数据里根本没这个字段）', () => {
    expect(text).not.toContain('证据等级')
  })
})

describe('EvidenceCard · 不重复面板已有的动作', () => {
  it('卡片里不出现「查看原文」「复制原文」——这两个要么和标题栏重复，要么点了没反应', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })
    const text = w.text()

    expect(text).not.toContain('查看原文')
    expect(text).not.toContain('复制原文')
    expect(text).not.toContain('复制结论')
    // 除折叠/展开外不该有多余按钮
    const labels = w.findAll('button').map((b) => b.text())
    expect(labels.every((t) => /展开|收起|显示上下文/.test(t))).toBe(true)
  })

  it('没有原文时也不冒出「复制结论」', () => {
    const ev = makeEvidence({ passage: null })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).not.toContain('复制')
  })
})

describe('EvidenceCard · 交互', () => {
  it('摘要默认折叠，点展开后取消 clamp', async () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.find('.ev-abstract').classes()).toContain('is-clamped')

    const toggle = w.findAll('.ev-toggle').find((b) => b.text() === '展开')
    await toggle!.trigger('click')

    expect(w.find('.ev-abstract').classes()).not.toContain('is-clamped')
  })

  it('换一篇文献后展开状态收回（否则上一条的展开会带过来）', async () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    await w.findAll('.ev-toggle').find((b) => b.text() === '展开')!.trigger('click')
    await w.find('.ev-more').trigger('click')
    expect(w.find('.ev-abstract').classes()).not.toContain('is-clamped')
    expect(w.find('.ev-ctx').exists()).toBe(true)

    await w.setProps({ evidence: makeEvidence({ doc_id: '8285' }) })

    expect(w.find('.ev-abstract').classes()).toContain('is-clamped')
    expect(w.find('.ev-ctx').exists()).toBe(false)
  })
})
