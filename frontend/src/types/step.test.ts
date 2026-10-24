import { describe, it, expect } from 'vitest'
import { normalizeStepStatus, isStepDone, isStepRunning } from './step'

/**
 * 前端镜像层：与后端 `app/domain/lifecycle.py` 保持一致。
 *
 * 这条契约曾经被破坏过 —— 前端把 `done` 映射成 `completed` 并写进类型，
 * 历史会话回放时勾选态丢失、步骤点不开。这里锁住"只认规范值"。
 */
describe('normalizeStepStatus', () => {
  it('保留 5 个规范值', () => {
    for (const s of ['pending', 'running', 'done', 'failed', 'skipped'] as const) {
      expect(normalizeStepStatus(s)).toBe(s)
    }
  })

  it('大小写与空白归一', () => {
    expect(normalizeStepStatus('DONE')).toBe('done')
    expect(normalizeStepStatus('  pending  ')).toBe('pending')
  })

  it('旧别名只在边界转换一次', () => {
    expect(normalizeStepStatus('completed')).toBe('done')
    expect(normalizeStepStatus('complete')).toBe('done')
    expect(normalizeStepStatus('success')).toBe('done')
    expect(normalizeStepStatus('error')).toBe('failed')
  })

  it('未知值降级为 pending，不抛错', () => {
    for (const bad of [undefined, null, '', 'weird', 123, {}, []]) {
      expect(normalizeStepStatus(bad)).toBe('pending')
    }
  })
})

describe('isStepDone / isStepRunning', () => {
  it('done 与 skipped 都算完成', () => {
    expect(isStepDone('done')).toBe(true)
    expect(isStepDone('skipped')).toBe(true)
    expect(isStepDone('pending')).toBe(false)
    expect(isStepDone('failed')).toBe(false)
    expect(isStepDone(undefined)).toBe(false)
  })

  it('pending 与 running 都算进行中', () => {
    expect(isStepRunning('pending')).toBe(true)
    expect(isStepRunning('running')).toBe(true)
    expect(isStepRunning('done')).toBe(false)
  })
})
