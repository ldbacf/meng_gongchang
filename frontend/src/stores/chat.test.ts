import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// store 顶层 import 了 api 模块；这里整体替换，避免测试触碰网络
vi.mock('@/api/chat', () => ({
  fetchConversationsApi: vi.fn(async () => []),
  createConversationApi: vi.fn(async () => ({ id: 'c1', title: 't', updatedAt: 0 })),
  fetchMessagesApi: vi.fn(async () => []),
  deleteConversationApi: vi.fn(async () => {}),
  renameConversationApi: vi.fn(async () => {}),
}))

import { useChatStore } from './chat'

describe('chat store — SSE 帧处理', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pending step 帧不携带 metrics（防止渲染未产出字段打崩 vdom）', () => {
    const s = useChatStore()
    s.startStreaming()

    s.handleStreamMsg({
      t: 'step',
      k: 'retrieval',
      s: 'pending',
      title: '检索',
    } as never)

    const step = s.streamRagSteps['retrieval']
    expect(step).toBeDefined()
    expect(step!.status).toBe('pending')
    // 关键回归：后端 frame_step 的 metrics 是 {}，空对象 truthy，
    // 若原样存下会让模板 v-if 放行并渲染 top_scores.length → undefined 抛错。
    expect(step!.metrics).toBeUndefined()

    s.stopReveal()
  })

  it('done step 帧保留 metrics', () => {
    const s = useChatStore()
    s.startStreaming()

    s.handleStreamMsg({
      t: 'step',
      k: 'fusion',
      s: 'done',
      title: '融合',
      metrics: { top_scores: [0.9, 0.8] },
    } as never)

    const step = s.streamRagSteps['fusion']
    expect(step).toBeDefined()
    // 契约：done 是规范值，前端不再映射成 completed（那层映射曾导致回放丢勾选态）
    expect(step!.status).toBe('done')
    expect(step!.metrics).toEqual({ top_scores: [0.9, 0.8] })

    s.stopReveal()
  })

  it('text 帧累加内容，cite 帧（数组）整组收集引用', () => {
    const s = useChatStore()
    s.startStreaming()

    s.handleStreamMsg({ t: 'text', c: '高血压' } as never)
    s.handleStreamMsg({ t: 'text', c: '初始治疗' } as never)
    // 后端一次发整组：{t:'cite', citations:[...]}，不是一条一帧
    s.handleStreamMsg({
      t: 'cite',
      citations: [
        { idx: '1', doc_id: '8060', title: '指南A', source: '中国全科医学', snippet: '片段A', relevance: 0.96 },
        { idx: '2', doc_id: '7611', title: '指南B', source: '中国全科医学', snippet: '片段B', relevance: 0.95 },
      ],
    } as never)

    expect(s.streamContent).toBe('高血压初始治疗')
    expect(s.streamCitations).toHaveLength(2)
    expect(s.streamCitations[0].id).toBe('1')
    expect(s.streamCitations[0].doc_id).toBe('8060')
    expect(s.streamCitations[1].doc_id).toBe('7611')
    // source 也要落进引用，否则「参考文献」列表里的期刊徽章是空白
    expect(s.streamCitations[0].source).toBe('中国全科医学')

    s.stopReveal()
  })

  it('cite 帧字段缺失时不产生"空引用"（回归：曾推入一条全 undefined 的引用）', () => {
    const s = useChatStore()
    s.startStreaming()

    // 空数组：不应产生任何引用（旧实现会 push 一条 undefined 引用 → 参考文献·1）
    s.handleStreamMsg({ t: 'cite', citations: [] } as never)
    expect(s.streamCitations).toHaveLength(0)

    s.stopReveal()
  })

  it('error 帧置错并停止 streaming，不把错误拼进正文', () => {
    const s = useChatStore()
    s.startStreaming()
    s.handleStreamMsg({ t: 'text', c: '部分回答' } as never)

    s.handleStreamMsg({ t: 'error', message: 'rag_error: boom' } as never)

    expect(s.streamError).toBe('rag_error: boom')
    expect(s.isStreaming).toBe(false)
    // 正文不含 [错误:...]（A-4.4 契约：错误走单独帧）
    expect(s.streamContent).toBe('部分回答')
  })
})
