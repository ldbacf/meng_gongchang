/**
 * 类型入口。
 *
 * `api.gen.ts` 由后端 OpenAPI 生成（命令见 `backend/tests/test_frontend_types.py`
 * 的 docstring），是**接口契约的唯一真相源**；手写类型只保留生成物覆盖不到的部分
 * （前端内部状态、SSE 帧、领域组合类型）。
 *
 * 走契约的写法：
 *   import type { components } from '@/types'
 *   type ConversationDTO = components['schemas']['ConversationResponse']
 *
 * 不要为了"看着方便"再手写一份响应结构 —— 那是重构前的老问题：
 * 后端加字段、前端不跟进，只能靠联调时才发现。
 */
export * from './api.gen'
export * from './auth'
export * from './chat'
export * from './knowledge'
export * from './step'
export * from './user'
