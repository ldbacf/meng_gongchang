<script setup lang="ts">
import type { RagSteps, RagStep, IntentMetrics, RetrievalMetrics, FusionMetrics, AnswerMetrics } from '@/types'
import { ref, computed, watch, nextTick } from 'vue'
import {
  ChevronRight, Search, Network, BarChart4, ShieldCheck,
  Clock, AlertTriangle, ArrowRight,
} from 'lucide-vue-next'

const props = defineProps<{
  steps: RagSteps
}>()

const expandedSteps = ref<Record<string, boolean>>({
  intent: false,
  retrieval: false,
  fusion: false,
  answer: false,
})

watch(
  () => props.steps,
  async (newSteps) => {
    if (!newSteps) return
    for (const [key, step] of Object.entries(newSteps)) {
      if (step && step.status === 'pending') {
        expandedSteps.value[key] = true
        await nextTick()
        const el = document.getElementById(`rag-step-${key}`)
        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  },
  { deep: true },
)

function toggleStep(key: string) {
  expandedSteps.value[key] = !expandedSteps.value[key]
}

function getStep(key: string): RagStep | undefined {
  return (props.steps as Record<string, RagStep | undefined>)[key]
}

// ── Intent helpers ──

function coverageColor(cov: string): string {
  switch (cov) {
    case 'high': return 'text-emerald-600 bg-emerald-50'
    case 'medium': return 'text-amber-600 bg-amber-50'
    case 'low': return 'text-orange-600 bg-orange-50'
    default: return 'text-red-600 bg-red-50'
  }
}

function coverageLabel(cov: string): string {
  switch (cov) {
    case 'high': return '高覆盖'
    case 'medium': return '中覆盖'
    case 'low': return '低覆盖'
    case 'out_of_domain': return '无覆盖'
    default: return '未知'
  }
}

// ── Retrieval helpers ──

function routingLabel(routing: string): string {
  switch (routing) {
    case 'both': return '双路召回'
    case 'milvus_only': return '仅向量检索'
    case 'es_only': return '仅全文检索'
    default: return routing
  }
}

// ── Fusion helpers ──

function scoreLabel(score: number): string {
  if (score >= 0.9) return '最优'
  if (score >= 0.75) return '优秀'
  if (score >= 0.6) return '相关'
  return '一般'
}

function scoreLabelColor(score: number): string {
  if (score >= 0.9) return 'text-emerald-600'
  if (score >= 0.75) return 'text-emerald-500'
  if (score >= 0.6) return 'text-amber-500'
  return 'text-slate-400'
}

// ── Step list ──

const stepList = computed(() => [
  {
    key: 'intent',
    icon: Search,
    colorClass: 'text-blue-600 bg-blue-50 border-blue-200',
    dotClass: 'bg-blue-400',
    lineClass: 'border-blue-200',
    label: '意图识别',
    sublabel: 'Query Rewriting',
  },
  {
    key: 'retrieval',
    icon: Network,
    colorClass: 'text-purple-600 bg-purple-50 border-purple-200',
    dotClass: 'bg-purple-400',
    lineClass: 'border-purple-200',
    label: '混合检索',
    sublabel: 'Hybrid Search',
  },
  {
    key: 'fusion',
    icon: BarChart4,
    colorClass: 'text-amber-600 bg-amber-50 border-amber-200',
    dotClass: 'bg-amber-400',
    lineClass: 'border-amber-200',
    label: '融合重排',
    sublabel: 'Reranking',
  },
  {
    key: 'answer',
    icon: ShieldCheck,
    colorClass: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    dotClass: 'bg-emerald-400',
    lineClass: 'border-emerald-200',
    label: '生成回答',
    sublabel: 'Answer Generation',
  },
])
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
    <div class="px-4 py-3">
      <div class="relative pl-6">
        <!-- Timeline line -->
        <div class="absolute left-[5px] top-2 bottom-2 w-px bg-slate-200" />

        <template v-for="(item, idx) in stepList" :key="item.key">
          <div
            v-if="getStep(item.key)"
            :id="`rag-step-${item.key}`"
            class="relative"
            :class="{ 'mb-3': idx < stepList.length - 1 }"
          >
            <!-- Dot -->
            <div class="absolute left-[-19px] top-1.5 z-10">
              <div
                v-if="getStep(item.key)?.status === 'completed'"
                class="flex h-[11px] w-[11px] items-center justify-center rounded-full border"
                :class="item.colorClass"
              >
                <div class="h-[5px] w-[5px] rounded-full" :class="item.dotClass" />
              </div>
              <span
                v-else
                class="block h-[11px] w-[11px] rounded-full animate-pulse"
                :class="item.dotClass"
              />
            </div>

            <!-- Header row -->
            <button
              class="flex w-full items-center gap-2 text-left"
              @click="toggleStep(item.key)"
            >
              <span class="text-xs font-medium text-slate-700">{{ item.label }}</span>
              <span class="text-[11px] text-slate-400">{{ item.sublabel }}</span>
              <span
                v-if="getStep(item.key)?.elapsed_ms"
                class="ml-auto mr-1 inline-flex items-center gap-0.5 text-[10px] text-slate-400"
              >
                <Clock :size="10" />
                {{ getStep(item.key)!.elapsed_ms! < 1000
                  ? `${getStep(item.key)!.elapsed_ms}ms`
                  : `${(getStep(item.key)!.elapsed_ms! / 1000).toFixed(1)}s` }}
              </span>
              <component
                :is="item.icon"
                :size="13"
                class="shrink-0"
                :class="getStep(item.key)?.status === 'completed' ? item.colorClass.split(' ')[0] : 'text-slate-300'"
              />
              <ChevronRight
                :size="12"
                class="text-slate-300 transition-transform duration-150 shrink-0"
                :class="{ 'rotate-90': expandedSteps[item.key] }"
              />
            </button>

            <!-- Expanded content -->
            <div
              v-if="expandedSteps[item.key] && getStep(item.key)"
              class="mt-1.5 rounded-md border px-3 py-2.5"
              :class="item.lineClass"
            >

              <!-- ── Intent step ── -->
              <template v-if="item.key === 'intent' && getStep(item.key)!.metrics">
                <div class="flex flex-wrap items-center gap-1.5 mb-2">
                  <span
                    class="inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-semibold border"
                    :class="coverageColor((getStep(item.key)!.metrics as IntentMetrics).coverage)"
                  >
                    {{ (getStep(item.key)!.metrics as IntentMetrics).coverage === 'high' ? '●' : '○' }}
                    {{ coverageLabel((getStep(item.key)!.metrics as IntentMetrics).coverage) }}
                  </span>
                  <span class="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 border border-blue-200">
                    {{ (getStep(item.key)!.metrics as IntentMetrics).domain }}
                  </span>
                </div>
                <p class="text-[11px] text-slate-500 leading-relaxed mb-1.5">
                  检索词：
                  <span class="font-medium text-slate-700">{{ (getStep(item.key)!.metrics as IntentMetrics).rewritten_query }}</span>
                </p>
                <div v-if="(getStep(item.key)!.metrics as IntentMetrics).keywords.length" class="flex flex-wrap gap-1 mb-1">
                  <span
                    v-for="kw in (getStep(item.key)!.metrics as IntentMetrics).keywords"
                    :key="kw"
                    class="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500"
                  >#{{ kw }}</span>
                </div>
                <div
                  v-if="(getStep(item.key)!.metrics as IntentMetrics).suggestion"
                  class="mt-1.5 flex items-start gap-1.5 rounded-md bg-amber-50 border border-amber-200 px-2 py-1.5"
                >
                  <AlertTriangle :size="11" class="text-amber-500 mt-0.5 shrink-0" />
                  <span class="text-[10px] text-amber-700 leading-relaxed">{{ (getStep(item.key)!.metrics as IntentMetrics).suggestion }}</span>
                </div>
              </template>

              <!-- ── Retrieval step ── -->
              <template v-if="item.key === 'retrieval' && getStep(item.key)!.metrics">
                <!-- Two-column source cards -->
                <div class="grid grid-cols-2 gap-3 mb-3">
                  <!-- Milvus -->
                  <div class="rounded-lg bg-purple-50/40 border border-purple-100 px-3 py-2">
                    <div class="text-[10px] text-purple-500 font-medium mb-0.5">向量检索 · Milvus</div>
                    <div class="text-2xl font-bold text-purple-600 leading-none mb-1.5">
                      {{ (getStep(item.key)!.metrics as RetrievalMetrics).milvus_hits }}
                    </div>
                    <div class="space-y-0.5">
                      <div
                        v-for="(doc, di) in (getStep(item.key)!.metrics as RetrievalMetrics).milvus_top_docs"
                        :key="'mv-' + di"
                        class="text-[10px] text-slate-500 truncate leading-relaxed"
                      >
                        <span class="text-slate-300 mr-0.5">·</span>{{ doc.title }}
                      </div>
                      <div
                        v-if="!(getStep(item.key)!.metrics as RetrievalMetrics).milvus_top_docs?.length"
                        class="text-[10px] text-slate-300 italic"
                      >无匹配结果</div>
                    </div>
                  </div>
                  <!-- ES -->
                  <div class="rounded-lg bg-amber-50/40 border border-amber-100 px-3 py-2">
                    <div class="text-[10px] text-amber-500 font-medium mb-0.5">全文检索 · ES</div>
                    <div class="text-2xl font-bold text-amber-600 leading-none mb-1.5">
                      {{ (getStep(item.key)!.metrics as RetrievalMetrics).es_hits }}
                    </div>
                    <div class="space-y-0.5">
                      <div
                        v-for="(doc, di) in (getStep(item.key)!.metrics as RetrievalMetrics).es_top_docs"
                        :key="'es-' + di"
                        class="text-[10px] text-slate-500 truncate leading-relaxed"
                      >
                        <span class="text-slate-300 mr-0.5">·</span>{{ doc.title }}
                      </div>
                      <div
                        v-if="!(getStep(item.key)!.metrics as RetrievalMetrics).es_top_docs?.length"
                        class="text-[10px] text-slate-300 italic"
                      >无匹配结果</div>
                    </div>
                  </div>
                </div>

                <!-- Divider -->
                <div class="border-t border-slate-200 mb-2" />

                <!-- RRF merge result -->
                <div class="flex items-center justify-between mb-1">
                  <span class="text-[11px] text-slate-500">RRF 融合去重</span>
                  <span class="text-sm font-bold text-slate-700">
                    {{ (getStep(item.key)!.metrics as RetrievalMetrics).after_dedup }} 条
                  </span>
                </div>
                <div class="text-[10px] text-slate-400 mb-2">
                  重叠 {{ (getStep(item.key)!.metrics as RetrievalMetrics).overlap }} 条
                </div>

                <!-- Routing badge -->
                <div class="text-center">
                  <span class="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                    {{ routingLabel((getStep(item.key)!.metrics as RetrievalMetrics).routing) }}
                  </span>
                </div>
              </template>

              <!-- ── Fusion step ── -->
              <template v-if="item.key === 'fusion' && getStep(item.key)!.metrics">
                <div class="flex items-center justify-center gap-2 mb-3">
                  <span class="text-[10px] text-slate-500">{{ (getStep(item.key)!.metrics as FusionMetrics).input_count }} 条</span>
                  <ArrowRight :size="12" class="text-slate-300" />
                  <span class="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                    Top-{{ (getStep(item.key)!.metrics as FusionMetrics).output_count }}
                  </span>
                </div>
                <p class="text-[10px] text-slate-400 text-center mb-2">
                  {{ (getStep(item.key)!.metrics as FusionMetrics).model }}
                </p>
                <!-- Score bars -->
                <div
                  v-if="(getStep(item.key)!.metrics as FusionMetrics).top_scores.length"
                  class="space-y-1.5"
                >
                  <div
                    v-for="(score, si) in (getStep(item.key)!.metrics as FusionMetrics).top_scores"
                    :key="si"
                    class="flex items-center gap-1.5"
                  >
                    <span class="text-[9px] text-slate-400 w-4 text-right">#{{ si + 1 }}</span>
                    <div class="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        class="h-full rounded-full bg-gradient-to-r from-emerald-400 via-emerald-300 to-amber-300 transition-all duration-500 ease-out"
                        :style="{ width: `${Math.max((score * 100), 2)}%` }"
                      />
                    </div>
                    <span class="text-[9px] font-mono text-slate-500 w-8">{{ (score * 100).toFixed(0) }}%</span>
                    <span class="text-[9px] w-5" :class="scoreLabelColor(score)">{{ scoreLabel(score) }}</span>
                  </div>
                </div>
              </template>

              <!-- ── Answer step ── -->
              <!-- Pending: summary + shimmer bar -->
              <template v-if="item.key === 'answer' && getStep(item.key)!.status === 'pending' && !getStep(item.key)!.metrics">
                <p class="text-xs text-slate-500 text-center mb-2 animate-pulse">
                  {{ getStep(item.key)!.summary || '正在生成回答...' }}
                </p>
                <div class="h-1 bg-slate-100 rounded-full overflow-hidden">
                  <div class="h-full rounded-full shimmer-bar w-1/2" />
                </div>
              </template>
              <!-- Completed: full metrics -->
              <template v-if="item.key === 'answer' && getStep(item.key)!.metrics">
                <div class="flex items-center justify-center gap-2 mb-1.5">
                  <span class="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                    {{ (getStep(item.key)!.metrics as AnswerMetrics).model }}
                  </span>
                  <span class="text-[9px] text-slate-400">
                    片段 ×{{ (getStep(item.key)!.metrics as AnswerMetrics).context_chunks }}
                  </span>
                </div>
                <div class="flex justify-center gap-3 text-[10px] text-slate-400">
                  <span>Token: {{ (getStep(item.key)!.metrics as AnswerMetrics).total_tokens }}</span>
                  <span v-if="(getStep(item.key)!.metrics as AnswerMetrics).total_elapsed_ms">
                    总耗时:
                    <span class="font-medium text-slate-600">
                      {{ ((getStep(item.key)!.metrics as AnswerMetrics).total_elapsed_ms / 1000).toFixed(1) }}s
                    </span>
                  </span>
                </div>
              </template>

              <!-- Generic fallback: pending step with summary (non-answer) -->
              <template
                v-if="
                  item.key !== 'answer' &&
                  getStep(item.key)!.status === 'pending' &&
                  getStep(item.key)!.summary &&
                  !getStep(item.key)!.metrics
                "
              >
                <p class="text-xs text-slate-500 text-center animate-pulse">
                  {{ getStep(item.key)!.summary }}
                </p>
              </template>

            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(200%); }
}

.shimmer-bar {
  background: linear-gradient(90deg, transparent 0%, #34d399 50%, transparent 100%);
  animation: shimmer 2s ease-in-out infinite;
}
</style>
