import type {
  LoginResponse,
  Conversation,
  Message,
  SystemUser,
} from '@/types'

// ── Global mock switch ──
export const USE_MOCK = false

// ── Auth ──
export const mockLoginResponse: LoginResponse = {
  access_token: 'mock-access-token',
  refresh_token: 'mock-refresh-token',
  token_type: 'bearer',
  user: { id: 'mock-id', username: 'admin', role: 'admin', enabled: true, last_login: null },
}

// ── Conversations ──
export const mockConversations: Conversation[] = [
  {
    id: 'conv-001',
    title: '基层全科医生心血管疾病风险评估',
    updatedAt: Date.now() - 60_000,
  },
  {
    id: 'conv-002',
    title: '慢阻肺合并高血压肺功能分析',
    updatedAt: Date.now() - 3600_000,
  },
  {
    id: 'conv-003',
    title: '基层卫生服务评价指标体系',
    updatedAt: Date.now() - 86_400_000,
  },
]

// ── Messages per conversation ──
export const mockMessages: Record<string, Message[]> = {
  'conv-001': [
    {
      id: 'msg-001-usr',
      role: 'user',
      content: '基层全科医生如何进行心血管疾病风险评估？',
      timestamp: Date.now() - 120_000,
    },
    {
      id: 'msg-001-ai',
      role: 'ai',
      content:
        '根据**《基层全科医生心血管疾病风险评估与沟通策略》**，基层全科医生可利用 China-PAR 模型等工具进行个体化评估。完整的风险沟通包含四步：风险评估、信息传递、行为干预和治疗决策。\n\n这有助于提高患者的健康认知与药物依从性。',
      citations: [
        {
          id: '101',
          title: '基层全科医生心血管疾病风险评估与沟通策略',
          source: '中华全科医师杂志',
          snippet:
            '基层全科医生可利用 China-PAR 模型、Framingham 风险评分等工具进行个体化心血管风险评估。风险沟通分为四步：风险评估、信息传递、行为干预和治疗决策。',
          page: 23,
          pdfUrl: '/api/pdf/1',
        },
      ],
      timestamp: Date.now() - 110_000,
    },
  ],
  'conv-002': [
    {
      id: 'msg-002-usr',
      role: 'user',
      content: 'COPD合并高血压患者的血压变异性与肺功能有什么关系？',
      timestamp: Date.now() - 3700_000,
    },
    {
      id: 'msg-002-ai',
      role: 'ai',
      content:
        '根据**《慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究》**显示，患者的 FEV1%pred 与收缩压及舒张压标准差均呈负相关。\n\n这意味着肺功能指标（FEV1%pred）越低，可能会导致血压变异性越高，临床中需特别关注。',
      citations: [
        {
          id: '102',
          title: '慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究',
          source: '中华结核和呼吸杂志',
          snippet:
            '研究显示，COPD 合并高血压患者的第1秒用力呼气容积占预计值百分比 (FEV1%pred) 与收缩压标准差 (SDSBP) 呈负线性相关。FEV1%pred 越低，血压变异性越高。',
          page: 56,
          pdfUrl: '/api/pdf/2',
        },
      ],
      timestamp: Date.now() - 3600_000,
    },
  ],
  'conv-003': [
    {
      id: 'msg-003-usr',
      role: 'user',
      content: '我国基层卫生服务评价指标体系的现状如何？',
      timestamp: Date.now() - 86_500_000,
    },
    {
      id: 'msg-003-ai',
      role: 'ai',
      content:
        '参考**《我国基层卫生服务与管理评价指标体系研究进展》**，目前相关研究主要聚焦6个方向。其中以"绩效评价"相关的研究数量最多，占比达36.9%。\n\n现阶段评价体系以定量硬指标占主导地位。',
      citations: [
        {
          id: '103',
          title: '我国基层卫生服务与管理评价指标体系研究进展',
          source: '中国卫生政策研究',
          snippet:
            '目前我国基层卫生评价指标主要聚焦于6类核心方向，其中以"绩效评价"为研究主题的文献数量最多（占36.9%），多采用文献分析法和德尔菲法构建指标体系。',
          page: 12,
          pdfUrl: '/api/pdf/3',
        },
      ],
      timestamp: Date.now() - 86_400_000,
    },
  ],
}

// ── Knowledge base documents ──
export const mockDocuments: any[] = [
  {
    id: 'doc-001',
    name: '基层全科医生心血管疾病风险评估与沟通策略.pdf',
    size: 2.4 * 1024 * 1024,
    status: 'ready',
    progress: 100,
    chunks: 86,
    uploadedAt: Date.now() - 7 * 86400000,
  },
  {
    id: 'doc-002',
    name: '慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究.pdf',
    size: 3.1 * 1024 * 1024,
    status: 'ready',
    progress: 100,
    chunks: 112,
    uploadedAt: Date.now() - 3 * 86400000,
  },
  {
    id: 'doc-003',
    name: '我国基层卫生服务与管理评价指标体系研究进展.pdf',
    size: 1.8 * 1024 * 1024,
    status: 'ready',
    progress: 100,
    chunks: 65,
    uploadedAt: Date.now() - 86400000,
  },
]

// ── Admin users ──
export const mockUsers: SystemUser[] = [
  {
    id: 'user-001',
    username: 'admin',
    role: 'admin',
    lastLogin: Date.now() - 60_000,
    enabled: true,
  },
  {
    id: 'user-002',
    username: 'doctor_zhang',
    role: 'user',
    lastLogin: Date.now() - 86_400_000,
    enabled: true,
  },
  {
    id: 'user-003',
    username: 'researcher_li',
    role: 'user',
    lastLogin: Date.now() - 7 * 86_400_000,
    enabled: false,
  },
]

// ── Simulate network delay ──
export function simulateDelay(ms = 200): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
