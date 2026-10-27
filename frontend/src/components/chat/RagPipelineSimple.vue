<script setup lang="ts">
import type { RagSteps, RagStep } from '@/types'
import { isStepDone, normalizeStepStatus } from '@/types/step'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { RAG_STEPS } from '@/constants/ragSteps'

const props = defineProps<{ steps: RagSteps }>()

// 步骤定义（顺序 / 中英标签）与 AiMessage 的待答文案共用 `constants/ragSteps`，
// 两处各写一份迟早会漂移。
const DEFS = RAG_STEPS

type StepKey = (typeof DEFS)[number]['key']

function get(key: StepKey): RagStep | undefined {
  return (props.steps as Record<string, RagStep | undefined>)[key]
}

/**
 * 完成判定走共享契约（`types/step.ts`）：`done` / `skipped` 都算走完。
 * 旧数据里的 `completed` 在边界由 `normalizeStepStatus` 归一，组件只认规范值。
 */
function isDone(step: RagStep | undefined): boolean {
  return isStepDone(normalizeStepStatus(step?.status))
}

/**
 * 只渲染**已经出现**的步骤。
 *
 * 后端按顺序发 step 事件（intent pending → done → retrieval pending …），
 * 所以"第 3、4 步还不存在"这件事天然成立，不需要额外的时间线代码。
 */
const rows = computed(() =>
  DEFS.filter((d) => get(d.key)).map((d) => ({ ...d, step: get(d.key) as RagStep })),
)

// ── 运行中的耗时与未判定进度 ──

const startAt = ref<Record<string, number>>({})
const now = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | undefined

watch(
  () => props.steps,
  (s) => {
    for (const d of DEFS) {
      if (s[d.key] && !startAt.value[d.key]) startAt.value[d.key] = Date.now()
    }
    const anyPending = rows.value.some((r) => r.step.status === 'pending')
    if (anyPending && !ticker) {
      ticker = setInterval(() => { now.value = Date.now() }, 100)
    } else if (!anyPending && ticker) {
      clearInterval(ticker)
      ticker = undefined
    }
  },
  { deep: true, immediate: true },
)

onBeforeUnmount(() => { if (ticker) clearInterval(ticker) })

function elapsed(key: StepKey): string {
  const step = get(key)
  if (!step) return ''
  if (step.elapsed_ms) return `${(step.elapsed_ms / 1000).toFixed(1)}s`
  if (step.status === 'pending') {
    const t0 = startAt.value[key]
    if (!t0) return '0.0s'
    return `${((now.value - t0) / 1000).toFixed(1)}s`
  }
  return ''
}

// ── 展开：默认折叠，点开才看过程 ──

const openKeys = ref<Set<string>>(new Set())
const populated = ref<Set<string>>(new Set())
const typed = ref<Record<string, string>>({})
const timers = new Map<string, ReturnType<typeof setInterval>>()

function isOpen(key: string): boolean {
  return openKeys.value.has(key)
}

function toggle(key: StepKey) {
  const step = get(key)
  if (!step || !isDone(step)) return

  const next = new Set(openKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
    if (!populated.value.has(key)) {
      populated.value = new Set(populated.value).add(key)
      typeSummary(key, step.summary ?? '')
    }
  }
  openKeys.value = next
}

/** 摘要逐字打出（只在首次展开时跑一次） */
function typeSummary(key: string, text: string) {
  if (!text) { typed.value[key] = ''; return }
  let i = 1
  // 先落第一个字，避免展开瞬间出现空白框
  typed.value[key] = text.slice(0, 1)
  const timer = setInterval(() => {
    i++
    typed.value[key] = text.slice(0, i)
    if (i >= text.length) {
      clearInterval(timer)
      timers.delete(key)
    }
  }, 24)
  timers.set(key, timer)
}

onBeforeUnmount(() => {
  timers.forEach((t) => clearInterval(t))
  timers.clear()
})

// ── metrics 渲染 ──

/** 缩写保持大写：es → ES、md5 → MD5 */
const ACRONYMS: Record<string, string> = {
  es: 'ES', md5: 'MD5', api: 'API', url: 'URL', id: 'ID', kb: 'KB', llm: 'LLM',
}

function prettyKey(k: string): string {
  return k
    .split('_')
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/**
 * 实时进度帧里的内部字段，不该出现在「指标明细」里。
 *
 * `live` 是标记位、`stage` 是内部阶段名、`es_total` 是进度分母 —— 它们服务于
 * 待答提示那句「已召回 12 篇」，对用户没有信息量。不过滤的话明细区会出现
 * 「live  true」「stage  es」这类噪声行。
 */
const INTERNAL_METRIC_KEYS = new Set(['live', 'stage', 'es_total'])

function metricEntries(key: StepKey): { k: string; v: string }[] {
  const m = get(key)?.metrics as Record<string, unknown> | undefined
  if (!m) return []
  return Object.entries(m)
    .filter(([k, v]) => !INTERNAL_METRIC_KEYS.has(k) && v !== null && v !== undefined && v !== '')
    .map(([k, v]) => {
      let text: string
      if (Array.isArray(v)) text = v.length > 4 ? `${v.slice(0, 4).join(', ')} …（共 ${v.length}）` : v.join(', ')
      else if (typeof v === 'object') text = JSON.stringify(v)
      else if (typeof v === 'number') text = Number.isInteger(v) ? String(v) : v.toFixed(3)
      else text = String(v)
      return { k: prettyKey(k), v: text }
    })
}
</script>

<template>
  <div class="py-0.5">
    <!-- 每个步骤包一层 slot：出现时高度从 0 长开 -->
    <div v-for="r in rows" :key="r.key" class="step-slot">
      <div class="step">
        <button
          class="row group/row"
          :class="{ 'is-clickable': isDone(r.step) }"
          @click="toggle(r.key)"
        >
          <!-- 状态点 -->
          <span
            class="grid h-[15px] w-[15px] shrink-0 place-items-center rounded-full border transition-colors duration-300"
            :class="{
              'border-ok bg-ok': isDone(r.step),
              'border-accent border-t-transparent animate-spin': r.step.status === 'pending',
            }"
          >
            <svg
              v-if="isDone(r.step)"
              class="dot-check"
              width="8" height="8" viewBox="0 0 24 24" fill="none"
              stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"
            ><path d="m4 12 5 5L20 6" /></svg>
          </span>

          <span class="text-[12.5px] font-medium" :class="isDone(r.step) ? 'text-ink-2' : 'text-ink'">
            {{ r.label }}
          </span>
          <span class="text-[11.5px] text-faint">{{ r.sub }}</span>

          <span class="ml-auto shrink-0 font-mono text-[11.5px] tabular-nums text-faint">
            {{ elapsed(r.key) }}
          </span>

          <ChevronDown
            v-if="isDone(r.step)"
            :size="12"
            class="shrink-0 text-faint transition-transform duration-300 ease-[cubic-bezier(.215,.61,.355,1)]"
            :class="{ 'rotate-180': isOpen(r.key) }"
          />
          <span v-else class="w-3 shrink-0" />
        </button>

        <!-- 运行中：不定长扫光条（后端没有百分比） -->
        <div v-if="r.step.status === 'pending'" class="sweep-bar">
          <i />
        </div>

        <!-- 明细：grid 0fr → 1fr -->
        <div
          class="grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(.215,.61,.355,1)]"
          :style="{ gridTemplateRows: isOpen(r.key) ? '1fr' : '0fr' }"
        >
          <div class="overflow-hidden">
            <div class="mb-1.5 ml-[22px] mt-1 rounded-md border border-line bg-canvas px-3 py-2.5">
              <p v-if="typed[r.key] || r.step.summary" class="mb-2 text-[12px] leading-relaxed text-ink-2">
                {{ typed[r.key] || r.step.summary }}
              </p>

              <div v-if="metricEntries(r.key).length" class="grid grid-cols-2 gap-x-5 gap-y-0.5">
                <div
                  v-for="(e, i) in metricEntries(r.key)"
                  :key="e.k"
                  class="metric-row flex items-baseline justify-between gap-2 border-b border-line py-0.5 text-[11px]"
                  :style="{ animationDelay: `${i * 80}ms` }"
                >
                  <span class="shrink-0 text-faint">{{ e.k }}</span>
                  <span class="truncate font-mono tabular-nums text-ink-2" :title="e.v">{{ e.v }}</span>
                </div>
              </div>

              <p v-else-if="!r.step.summary" class="text-[11.5px] text-faint">该步骤暂无明细</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 步骤出现：高度从 0 长开 + 轻微上移淡入 */
.step-slot {
  animation: slot-in 0.36s var(--ease-out) both;
}

@keyframes slot-in {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.row {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  margin: -2px -6px;
  padding: 4px 6px;
  border-radius: 6px;
  text-align: left;
  transition: background-color 0.15s;
}

.row.is-clickable { cursor: pointer; }
.row.is-clickable:hover { background: var(--surface); }

/* 勾选弹入（欠阻尼微弹） */
.dot-check {
  animation: check-pop 0.4s var(--ease-spring-soft) both;
}

@keyframes check-pop {
  0% { transform: scale(0.4); opacity: 0; }
  60% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(1); }
}

/* 运行中的不定长扫光 */
.sweep-bar {
  position: relative;
  height: 2px;
  margin: 3px 0 4px 24px;
  border-radius: 2px;
  background: var(--line);
  overflow: hidden;
}

.sweep-bar > i {
  position: absolute;
  inset: 0;
  width: 40%;
  border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: sweep-x 1.5s var(--ease) infinite;
}

@keyframes sweep-x {
  from { transform: translateX(-110%); }
  to { transform: translateX(310%); }
}

/* 指标错开浮现 */
.metric-row {
  opacity: 0;
  filter: blur(4px);
  animation: metric-in 0.42s var(--ease-out) forwards;
}

@keyframes metric-in {
  to {
    opacity: 1;
    filter: blur(0);
  }
}
</style>
