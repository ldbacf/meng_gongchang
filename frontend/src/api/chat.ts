import api from './index'
import type { components, Conversation, Message, RagStep, RagSteps } from '@/types'

/**
 * 后端响应类型一律取自生成物 `api.gen.ts`（由 OpenAPI 生成），
 * 本地只做「DTO → 前端模型」的映射（日期转毫秒、字段改名）。
 *
 * 以前这里写的是 `(res.data as any[])`，等于把契约检查整个绕过去了：
 * 后端改字段前端不报错，只能等联调时白屏才发现。
 */
type ConversationDTO = components['schemas']['ConversationResponse']
type MessageDTO = components['schemas']['MessageResponse']

/**
 * `rag_steps` 在生成物里是 `Record<string, RagStepSchema>`，前端模型是
 * `RagSteps`（四个具名键）。这里按已知键收窄，未知键丢弃。
 */
const KNOWN_STEPS = ['intent', 'retrieval', 'fusion', 'answer'] as const

export async function fetchConversationsApi(): Promise<Conversation[]> {
  const res = await api.get<ConversationDTO[]>('/v1/conversations')
  return res.data.map(toConversation)
}

export async function createConversationApi(title?: string): Promise<Conversation> {
  const res = await api.post<ConversationDTO>('/v1/conversations', {
    title: title ?? '新对话',
  })
  return toConversation(res.data)
}

export async function renameConversationApi(id: string, title: string): Promise<void> {
  return api.patch(`/v1/conversations/${id}`, { title })
}

export async function fetchMessagesApi(conversationId: string): Promise<Message[]> {
  const res = await api.get<MessageDTO[]>(`/v1/conversations/${conversationId}/messages`)
  return res.data.map((m) => ({
    id: m.id,
    // 后端 role 是 str；前端模型收窄成联合类型，未知值按 ai 处理而不是崩
    role: m.role === 'user' ? ('user' as const) : ('ai' as const),
    content: m.content,
    citations: (m.citations ?? []).map((c) => ({
      id: c.id,
      title: c.title,
      source: c.source,
      snippet: c.snippet,
      page: c.page ?? undefined,
      doc_id: c.doc_id ?? undefined,
      relevance: c.relevance,
    })),
    ragSteps: mapRagSteps(m.rag_steps),
    timestamp: new Date(m.created_at).getTime(),
  }))
}

export async function deleteConversationApi(id: string): Promise<void> {
  return api.delete(`/v1/conversations/${id}`)
}

function toConversation(c: ConversationDTO): Conversation {
  return {
    id: c.id,
    title: c.title,
    updatedAt: new Date(c.updated_at).getTime(),
  }
}

function mapRagSteps(steps: MessageDTO['rag_steps']): RagSteps | undefined {
  if (!steps) return undefined
  const out: RagSteps = {}
  for (const key of KNOWN_STEPS) {
    const raw = steps[key]
    if (raw) out[key] = raw as unknown as RagStep
  }
  return out
}
