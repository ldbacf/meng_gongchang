<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import type { Citation, RagSteps } from '@/types'
import { fetchDocumentPdfApi } from '@/api/document'
import ChatInput from './ChatInput.vue'
import MessageBubble from './MessageBubble.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import CitationSummary from './CitationSummary.vue'
import RightPanel from './RightPanel.vue'
import { Sparkles } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()

const messagesContainer = ref<HTMLElement | null>(null)
const mockRagSteps = reactive<RagSteps>({})
const mockTimers: ReturnType<typeof setTimeout>[] = []

const streamMessage = {
  id: 'streaming',
  role: 'ai' as const,
  content: '',
  timestamp: Date.now(),
}

const streamMessageWithRagSteps = computed(() => ({
  ...streamMessage,
  ragSteps: mockRagSteps,
}))

// ── Right panel state ──

const rightPanelOpen = ref(false)
const activeCitation = ref<Citation | null>(null)
const pdfUrl = ref<string | null>(null)
const pdfLoading = ref(false)

const uniqueCitations = computed(() => {
  const map = new Map<string, Citation>()
  for (const msg of chatStore.messages) {
    for (const cite of msg.citations ?? []) {
      if (!map.has(cite.id)) {
        map.set(cite.id, cite)
      }
    }
  }
  return Array.from(map.values())
})

async function handleCitationClick(citationId: string) {
  const citation = uniqueCitations.value.find((c) => c.id === citationId)
  if (!citation) return

  activeCitation.value = citation
  rightPanelOpen.value = true
  pdfLoading.value = true
  pdfUrl.value = null

  try {
    // Determine docId from citation: citation 101 → doc-001, 102 → doc-002, 103 → doc-003
    const docNum = parseInt(citationId, 10)
    const docId = isNaN(docNum) ? null : `doc-${String(docNum - 100).padStart(3, '0')}`
    if (docId) {
      const res = await fetchDocumentPdfApi(docId)
      pdfUrl.value = res.pdfUrl
    }
  } catch {
    // Fallback: use citation's built-in pdfUrl if API fails
    pdfUrl.value = citation.pdfUrl ?? null
  } finally {
    pdfLoading.value = false
  }
}

function showCitationList() {
  activeCitation.value = null
  pdfUrl.value = null
  rightPanelOpen.value = true
}

function closeRightPanel() {
  rightPanelOpen.value = false
  activeCitation.value = null
  pdfUrl.value = null
}

function goBackToList() {
  activeCitation.value = null
  pdfUrl.value = null
}

function handlePanelSelectCitation(citation: Citation) {
  handleCitationClick(citation.id)
}

// ── Mock pipeline ──

function clearMockTimers() {
  mockTimers.forEach(clearTimeout)
  mockTimers.length = 0
}

onUnmounted(clearMockTimers)

function resetRagSteps() {
  delete mockRagSteps.intent
  delete mockRagSteps.retrieval
  delete mockRagSteps.fusion
  delete mockRagSteps.evaluation
}

type Scenario = 'cardiovascular' | 'copd' | 'evaluation' | 'default'

interface ScenarioConfig {
  intentSummary: string
  retrievalSummary: string
  fusionSummary: string
  responseText: string
  citations: Citation[]
}

const scenarioConfigs: Record<Scenario, ScenarioConfig> = {
  cardiovascular: {
    intentSummary: '"全科医生", "心血管疾病", "风险评估"',
    retrievalSummary:
      'Milvus 向量库召回《基层全科医生心血管疾病风险评估与沟通策略》等 24 个片段，去重后保留 12 个。',
    fusionSummary:
      '应用 BGE-Reranker-v2 重排序，精选 Top-5 高匹配度内容。',
    responseText:
      '根据**《基层全科医生心血管疾病风险评估与沟通策略》**，基层全科医生可利用 China-PAR 模型等工具进行个体化评估。完整的风险沟通包含四步：风险评估、信息传递、行为干预和治疗决策。[101]\n\n这有助于提高患者的健康认知与药物依从性。',
    citations: [
      {
        id: '101',
        title: '基层全科医生心血管疾病风险评估与沟通策略',
        source: '中华全科医师杂志',
        snippet:
          '基层全科医生可利用 China-PAR 模型、Framingham 风险评分等工具进行个体化心血管风险评估。风险沟通分为四步：风险评估、信息传递、行为干预和治疗决策。',
        page: 23,
        pdfUrl: '/pdf/基层全科医生心血管疾病风险评估与沟通策略.pdf',
      },
    ],
  },
  copd: {
    intentSummary: '"COPD", "高血压", "血压变异性"',
    retrievalSummary:
      'Milvus 向量库召回《慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究》等 31 个片段，去重后保留 16 个。',
    fusionSummary:
      '应用 BGE-Reranker-v2 重排序，精选 Top-5 高匹配度内容。',
    responseText:
      '根据**《慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究》**显示，患者的 FEV1%pred 与收缩压及舒张压标准差均呈负相关。[102]\n\n这意味着肺功能指标（FEV1%pred）越低，可能会导致血压变异性越高，临床中需特别关注。',
    citations: [
      {
        id: '102',
        title: '慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究',
        source: '中华结核和呼吸杂志',
        snippet:
          '研究显示，COPD 合并高血压患者的第1秒用力呼气容积占预计值百分比 (FEV1%pred) 与收缩压标准差 (SDSBP) 呈负线性相关。FEV1%pred 越低，血压变异性越高。',
        page: 56,
        pdfUrl: '/pdf/慢性阻塞性肺疾病合并高血压患者肺功能与血压变异性的相关研究.pdf',
      },
    ],
  },
  evaluation: {
    intentSummary: '"基层卫生服务", "评价指标体系"',
    retrievalSummary:
      'Milvus 向量库召回《我国基层卫生服务与管理评价指标体系研究进展》等 19 个片段，去重后保留 9 个。',
    fusionSummary:
      '应用 BGE-Reranker-v2 重排序，精选 Top-5 高匹配度内容。',
    responseText:
      '参考**《我国基层卫生服务与管理评价指标体系研究进展》**，目前相关研究主要聚焦6个方向。其中以"绩效评价"相关的研究数量最多，占比达36.9%。[103]\n\n现阶段评价体系以定量硬指标占主导地位。',
    citations: [
      {
        id: '103',
        title: '我国基层卫生服务与管理评价指标体系研究进展',
        source: '中国卫生政策研究',
        snippet:
          '目前我国基层卫生评价指标主要聚焦于6类核心方向，其中以"绩效评价"为研究主题的文献数量最多（占36.9%），多采用文献分析法和德尔菲法构建指标体系。',
        page: 12,
        pdfUrl: '/pdf/我国基层卫生服务与管理评价指标体系研究进展.pdf',
      },
    ],
  },
  default: {
    intentSummary: '"医学文献", "循证检索"',
    retrievalSummary:
      'Milvus 向量库及 ES 共同召回了 28 个医学相关片段，去重后保留 15 个。',
    fusionSummary:
      '应用 BGE-Reranker-v2 重排序，精选 Top-5 高匹配度内容。',
    responseText:
      '根据知识库检索结果，未找到与您问题高度匹配的特定文献。建议您尝试使用更具体的医学关键词，如"心血管风险评估"、"COPD肺功能"或"基层卫生评价指标"进行查询。[100]',
    citations: [
      {
        id: '100',
        title: 'MedRAG 系统检索提示',
        source: '系统消息',
        snippet:
          '请使用具体医学关键词查询，如：心血管风险评估、COPD合并高血压、基层卫生服务评价指标体系等。',
      },
    ],
  },
}

function detectScenario(content: string): Scenario {
  const lower = content.toLowerCase()
  if (/心血管|全科/.test(lower)) return 'cardiovascular'
  if (/copd|阻塞|高血压/.test(lower)) return 'copd'
  if (/评价|基层卫生/.test(lower)) return 'evaluation'
  return 'default'
}

function runMockPipeline(userMessage: string) {
  clearMockTimers()
  const scenario = detectScenario(userMessage)
  const config = scenarioConfigs[scenario]

  mockRagSteps.intent = { status: 'pending', title: '意图识别' }
  mockRagSteps.retrieval = { status: 'pending', title: '混合检索' }
  mockRagSteps.fusion = { status: 'pending', title: '融合重排' }
  mockRagSteps.evaluation = { status: 'pending', title: '门神评估' }

  mockTimers.push(setTimeout(() => {
    mockRagSteps.intent!.status = 'completed'
    mockRagSteps.intent!.summary = config.intentSummary
  }, 500))

  mockTimers.push(setTimeout(() => {
    mockRagSteps.retrieval!.status = 'completed'
    mockRagSteps.retrieval!.summary = config.retrievalSummary
  }, 1000))

  mockTimers.push(setTimeout(() => {
    mockRagSteps.fusion!.status = 'completed'
    mockRagSteps.fusion!.summary = config.fusionSummary
  }, 1500))

  mockTimers.push(setTimeout(() => {
    mockRagSteps.evaluation!.status = 'completed'
    streamMockText(config.responseText, config.citations)
  }, 2000))
}

function streamMockText(text: string, citations: Citation[]) {
  let i = 0
  const interval = setInterval(() => {
    if (i < text.length) {
      chatStore.streamContent += text[i]
      i++
    } else {
      clearInterval(interval)
      mockTimers.splice(mockTimers.indexOf(interval), 1)

      for (const cite of citations) {
        chatStore.addStreamCitation(cite)
      }

      chatStore.finishStreaming()
      const lastMsg = chatStore.messages[chatStore.messages.length - 1]
      if (lastMsg && lastMsg.role === 'ai') {
        lastMsg.ragSteps = { ...mockRagSteps }
      }
      resetRagSteps()
    }
  }, 40)
  mockTimers.push(interval)
}

// ── Lifecycle ──

onMounted(async () => {
  await chatStore.fetchConversations()

  const convId = route.params.id as string | undefined
  if (convId) {
    chatStore.selectConversation(convId)
  }
})

function abortStreaming() {
  clearMockTimers()
  resetRagSteps()
  if (chatStore.isStreaming) {
    chatStore.isStreaming = false
    chatStore.streamContent = ''
    chatStore.streamCitations = []
  }
}

watch(
  () => route.params.id,
  async (newId) => {
    abortStreaming()
    if (newId && typeof newId === 'string') {
      chatStore.selectConversation(newId)
    } else {
      chatStore.currentConversationId = null
      chatStore.messages = []
    }
  },
)

watch(
  () => [chatStore.messages.length, chatStore.streamContent],
  async () => {
    await nextTick()
    messagesContainer.value?.lastElementChild?.scrollIntoView({
      behavior: 'smooth',
    })
  },
)

async function handleSend(content: string) {
  if (!chatStore.currentConversationId) {
    const id = await chatStore.createConversation()
    router.replace(`/chat/${id}`)
  }

  chatStore.addUserMessage(content)
  chatStore.startStreaming()

  runMockPipeline(content)
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left: Chat main -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <!-- Messages Area -->
      <div
        ref="messagesContainer"
        class="flex-1 overflow-y-auto"
      >
        <!-- Empty state -->
        <div
          v-if="!chatStore.currentConversationId && !chatStore.isStreaming"
          class="flex h-full flex-col items-center justify-center px-4"
        >
          <div
            class="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-sky-400 shadow-lg mb-6"
          >
            <Sparkles :size="32" class="text-white" />
          </div>
          <h2 class="text-xl font-semibold text-slate-800 mb-2">
            MedRAG 医学文献助手
          </h2>
          <p class="max-w-md text-center text-sm text-slate-500 leading-relaxed">
            基于 RAG 技术的医学文献智能问答系统。点击左侧「发起新对话」开始提问，获取基于真实文献的精准回答。
          </p>
        </div>

        <!-- Messages -->
        <template v-for="msg in chatStore.messages" :key="msg.id">
          <MessageBubble
            :message="msg"
            @citation-click="handleCitationClick"
          />
        </template>

        <!-- Live streaming message -->
        <div v-if="chatStore.isStreaming">
          <MessageBubble
            :message="streamMessageWithRagSteps"
            :is-streaming="true"
            :stream-content="chatStore.streamContent"
          />
        </div>

        <LoadingSpinner
          v-if="chatStore.messages.length === 0 && chatStore.isStreaming"
          text="正在思考..."
        />

        <!-- Citation summary oval -->
        <CitationSummary
          v-if="uniqueCitations.length > 0 && !chatStore.isStreaming"
          :count="uniqueCitations.length"
          @click="showCitationList"
        />
      </div>

      <!-- Input -->
      <ChatInput :disabled="chatStore.isStreaming" @send="handleSend" />
    </div>

    <!-- Right: Citation panel -->
    <RightPanel
      v-if="rightPanelOpen"
      :citations="uniqueCitations"
      :active-citation="activeCitation"
      :pdf-url="pdfUrl"
      :pdf-loading="pdfLoading"
      @close="closeRightPanel"
      @back-to-list="goBackToList"
      @select-citation="handlePanelSelectCitation"
    />
  </div>
</template>
