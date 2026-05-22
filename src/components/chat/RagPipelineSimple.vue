<script setup lang="ts">
import type { RagSteps, RagStep } from '@/types'
import { ref, computed } from 'vue'
import { ChevronDown, ChevronRight, Search, Network, BarChart4, ShieldCheck } from 'lucide-vue-next'

const props = defineProps<{
  steps: RagSteps
}>()

const isExpanded = ref(true)
const expandedSteps = ref<Record<string, boolean>>({
  intent: false,
  retrieval: false,
  fusion: false,
  evaluation: false,
})

function toggleStep(key: string) {
  expandedSteps.value[key] = !expandedSteps.value[key]
}

function getStep(key: string): RagStep | undefined {
  return (props.steps as Record<string, RagStep | undefined>)[key]
}

const stepList = computed(() => [
  {
    key: 'intent',
    icon: Search,
    colorClass: 'text-blue-600 bg-blue-50 border-blue-300',
    dotClass: 'bg-blue-400',
    lineClass: 'border-blue-200',
    label: '意图识别',
    sublabel: 'Query Rewriting',
    getContent: (s: RagStep) =>
      `提取关键实体与意图：${s.summary || '营收下降原因, 2024年度财报, 同比分析'}`,
  },
  {
    key: 'retrieval',
    icon: Network,
    colorClass: 'text-purple-600 bg-purple-50 border-purple-300',
    dotClass: 'bg-purple-400',
    lineClass: 'border-purple-200',
    label: '混合检索',
    sublabel: 'Hybrid Search',
    getContent: (s: RagStep) =>
      s.summary ||
      'Milvus 向量库及 ES 共同召回了 28 个片段，去重后保留 15 个高相关文档片段。',
  },
  {
    key: 'fusion',
    icon: BarChart4,
    colorClass: 'text-amber-600 bg-amber-50 border-amber-300',
    dotClass: 'bg-amber-400',
    lineClass: 'border-amber-200',
    label: '融合重排',
    sublabel: 'Reranking',
    getContent: (s: RagStep) =>
      s.summary ||
      '应用 BGE-Reranker-v2 算法对候选片段进行语义重排序，精选出 Top-5 高匹配度内容。',
  },
  {
    key: 'evaluation',
    icon: ShieldCheck,
    colorClass: 'text-emerald-600 bg-emerald-50 border-emerald-300',
    dotClass: 'bg-emerald-400',
    lineClass: 'border-emerald-200',
    label: '门神评估',
    sublabel: 'CRAG Routing',
    getContent: (_s: RagStep) =>
      `<span class="inline-flex items-center gap-1.5 rounded-md bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 border border-emerald-200">✅ 判定：存在高相关性上下文，准许大模型生成回复。</span>`,
  },
])
</script>

<template>
  <div class="mb-4 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
    <!-- Header -->
    <button
      class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-50 transition-colors"
      @click="isExpanded = !isExpanded"
    >
      <span class="text-sm font-semibold text-slate-700">系统检索分析过程</span>
      <ChevronDown
        :size="16"
        class="text-slate-400 transition-transform duration-200"
        :class="{ 'rotate-180': isExpanded }"
      />
    </button>

    <!-- Pipeline Steps -->
    <div
      v-if="isExpanded"
      class="border-t border-slate-100 px-4 py-3"
    >
      <div class="relative pl-6">
        <!-- Vertical guide line -->
        <div class="absolute left-[5px] top-2 bottom-2 w-px bg-slate-200" />

        <div
          v-for="(item, idx) in stepList"
          :key="item.key"
          class="relative"
          :class="{ 'mb-3': idx < stepList.length - 1 }"
        >
          <!-- Step dot & line -->
          <div class="absolute left-[-19px] top-1.5 z-10">
            <!-- Completed icon -->
            <div
              v-if="getStep(item.key)?.status === 'completed'"
              class="flex h-[11px] w-[11px] items-center justify-center rounded-full border"
              :class="item.colorClass"
            >
              <div class="h-[5px] w-[5px] rounded-full" :class="item.dotClass" />
            </div>
            <!-- Pending pulse dot -->
            <span
              v-else
              class="block h-[11px] w-[11px] rounded-full animate-pulse"
              :class="item.dotClass"
            />
          </div>

          <!-- Step header (clickable to expand) -->
          <button
            class="flex w-full items-center gap-2 text-left"
            @click="toggleStep(item.key)"
          >
            <span class="text-xs font-medium text-slate-700">
              {{ item.label }}
            </span>
            <span class="text-[11px] text-slate-400">
              {{ item.sublabel }}
            </span>
            <component
              :is="item.icon"
              :size="13"
              class="ml-auto"
              :class="getStep(item.key)?.status === 'completed' ? item.colorClass.split(' ')[0] : 'text-slate-300'"
            />
            <ChevronRight
              :size="12"
              class="text-slate-300 transition-transform duration-150"
              :class="{ 'rotate-90': expandedSteps[item.key] }"
            />
          </button>

          <!-- Expanded detail -->
          <div
            v-if="expandedSteps[item.key] && getStep(item.key)"
            class="mt-1.5 rounded-md border bg-white px-3 py-2"
            :class="item.lineClass"
          >
            <p
              class="text-xs leading-relaxed text-slate-600"
              v-html="item.getContent(getStep(item.key)!)"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
