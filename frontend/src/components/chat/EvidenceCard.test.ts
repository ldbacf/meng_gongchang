import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EvidenceCard from './EvidenceCard.vue'
import type { EvidenceResponse } from '@/api/citation'

/**
 * 证据卡组件测试。
 *
 * 重点不是「渲染了没」，而是**缺数据时的行为对不对**：
 * 这些分支在真实语料里各占一部分（指南无结论段、Meta 只有篇数没有例数、
 * 综述什么都没有），如果它们退化成「显示 0」或「编一段结论」，
 * 用户会被误导 —— 这比渲染不出来严重得多。
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
      prev_heading: '2.3 基因位点表达分析',
      prev_text: '与药物作用靶点敏感性基因多态性位点相关的是 ADRB1、ACEI。',
      hit_heading: '2 结果 → 2.4 用药对血压的影响',
      hit_paragraphs: ['A6986G:CYP3A5*1/*1（AA）患者 M3、M6 舒张压低于 M0。'],
      next_heading: '2.5 两组干预前后比较',
      next_text: 'M3、M6 基因导向组 Hcy 水平低于基因组。',
      has_prev: true,
      has_next: true,
    },
    md5: '2ce5cd27ae33c0d8e4dc30962426cc54',
    message: '',
    ...over,
  }
}

const baseProps = { loading: false, pdfAvailable: true }

describe('EvidenceCard', () => {
  it('渲染证据卡的核心字段', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.text()).toContain('社区H型高血压患者')
    expect(w.text()).toContain('中国全科医学')
    expect(w.text()).toContain('2024')
    expect(w.text()).toContain('样本量 200 例')
  })

  it('有结论段时直接展示结论，并标出来源是 abstract_cn', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.text()).toContain('个体化用药效果显著')
    expect(w.text()).toContain('abstract_cn · 结论')
    // 有结论时不该出现降级说明
    expect(w.text()).not.toContain('本文摘要没有「结论」段')
  })

  it('没有结论段时降级到命中段落首句，并明确说明这不是作者结论', () => {
    // 真实样本：8285 指南，sections 为空
    const ev = makeEvidence({
      abstract_sections: [],
      has_conclusion: false,
      sample_size: null,
      passage: {
        ...makeEvidence().passage!,
        hit_paragraphs: ['降压药物优先选用 ACEI/ARB，降压效果不佳酌情加用 CCB。'],
      },
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).toContain('降压药物优先选用 ACEI/ARB')
    // 关键：必须显式告知用户这是降级结果，不能假装它是结论
    expect(w.text()).toContain('本文摘要没有「结论」段')
    expect(w.text()).toContain('337')
  })

  it('「纳入 18 篇」标成纳入文献数，不标成样本量', () => {
    // 真实样本：8416 Meta 分析
    const ev = makeEvidence({
      sample_size: { value: 18, unit: '篇', is_subject_count: false },
    })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).toContain('纳入 18 篇')
    expect(w.text()).not.toContain('样本量 18')
  })

  it('没有样本量时不渲染该标签（不显示 0）', () => {
    const ev = makeEvidence({ sample_size: null })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.text()).not.toContain('样本量')
    expect(w.text()).not.toContain('纳入')
  })

  it('上下文按 上文 → 命中 → 下文 的顺序渲染成连续文本', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })
    const passage = w.find('.ev-passage')
    const text = passage.text()

    const iPrev = text.indexOf('2.3 基因位点表达分析')
    const iHit = text.indexOf('2.4 用药对血压的影响')
    const iNext = text.indexOf('2.5 两组干预前后比较')

    expect(iPrev).toBeGreaterThanOrEqual(0)
    expect(iHit).toBeGreaterThan(iPrev)
    expect(iNext).toBeGreaterThan(iHit)
  })

  it('命中段落被单独包裹（能高亮），上下文用褪色类', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    expect(w.findAll('.ev-passage-hit').length).toBe(1)
    expect(w.find('.ev-passage-hit').text()).toContain('舒张压低于 M0')
    expect(w.findAll('.ev-passage-nb').length).toBe(2) // 上文 + 下文
  })

  it('「只看命中」隐藏前后文', async () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    const toggle = w.findAll('.ev-toggle').find((b) => b.text().includes('只看命中'))
    expect(toggle).toBeTruthy()

    await toggle!.trigger('click')

    expect(w.find('.ev-passage').classes()).toContain('only-hit')
    expect(toggle!.text()).toBe('显示前后文')
  })

  it('没有 passage 时回落到 message 提示，不渲染上下文区', () => {
    const ev = makeEvidence({ passage: null, message: '未在解析结果中找到该片段' })
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    expect(w.find('.ev-passage').exists()).toBe(false)
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
    expect(w.text()).toContain('无结论段')
  })

  it('加载态显示占位文案而不是空面板', () => {
    const w = mount(EvidenceCard, { props: { loading: true, pdfAvailable: true, evidence: null } })
    expect(w.text()).toContain('加载文献信息')
  })

  it('无数据且非加载态显示空态', () => {
    const w = mount(EvidenceCard, { props: { loading: false, pdfAvailable: false, evidence: null } })
    expect(w.text()).toContain('暂无该文献的详细信息')
  })

  it('点「查看原文 PDF」抛 openPdf，点「复制结论」抛 copy', async () => {
    const ev = makeEvidence()
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: ev } })

    const pdfBtn = w.findAll('button').find((b) => b.text().includes('查看原文 PDF'))
    const copyBtn = w.findAll('button').find((b) => b.text().includes('复制结论'))
    expect(pdfBtn).toBeTruthy()
    expect(copyBtn).toBeTruthy()

    await pdfBtn!.trigger('click')
    await copyBtn!.trigger('click')

    expect(w.emitted('openPdf')).toHaveLength(1)
    const copied = w.emitted('copy')?.[0]?.[0] as string
    expect(copied).toContain('个体化用药效果显著')
  })

  it('pdf 不可用时不显示「查看原文 PDF」', () => {
    const w = mount(EvidenceCard, {
      props: { loading: false, pdfAvailable: false, evidence: makeEvidence() },
    })
    expect(w.text()).not.toContain('查看原文 PDF')
  })

  it('全文没有任何「证据等级」字样（数据里根本没有这个字段）', () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })
    expect(w.text()).not.toContain('证据等级')
  })

  it('摘要默认折叠，点展开后取消 clamp', async () => {
    const w = mount(EvidenceCard, { props: { ...baseProps, evidence: makeEvidence() } })

    const abs = w.find('.ev-abstract')
    expect(abs.classes()).toContain('ev-clamped')

    const toggle = w.findAll('.ev-toggle').find((b) => b.text() === '展开')
    await toggle!.trigger('click')

    expect(w.find('.ev-abstract').classes()).not.toContain('ev-clamped')
  })
})
