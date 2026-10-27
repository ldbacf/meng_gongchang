<script setup lang="ts">
import type { Citation, Message } from '@/types'
import { useMarkdown } from '@/composables/useMarkdown'
import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { useChatStore } from '@/stores/chat'
import RagPipelineSimple from './RagPipelineSimple.vue'
import {
  currentRunningStep,
  splitCountTemplate,
  stepHint,
} from '@/constants/ragSteps'
import type { StepHint } from '@/constants/ragSteps'
import { Copy, Check, ThumbsUp, RotateCw, BookOpen, ChevronDown, AlertCircle } from 'lucide-vue-next'

const chatStore = useChatStore()

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
  /** 只有最后一条 AI 回答允许重新生成（历史回答重生成会让后面对话失去上下文） */
  canRegenerate?: boolean
}>()

const emit = defineEmits<{
  'citation-click': [citation: Citation]
  'show-citation-list': []
  regenerate: []
}>()

const { render } = useMarkdown()

const renderedContent = computed(() => {
  const content =
    props.isStreaming && props.streamContent !== undefined
      ? props.streamContent
      : props.message.content
  return render(content)
})

function handleContentClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('.citation-tag') as HTMLElement | null
  const cid = target?.dataset.citationId
  if (!cid) return
  // 在**本消息**的引用里解析，而不是全局按序号查 —— 序号（"1".."5"）是每条回答内部的编号，
  // 跨消息重复；曾用全局 map 按 id 去重，多轮会话里点 [2] 会打开上一轮的文献。
  const cite = props.message.citations?.find((c) => String(c.id) === cid)
  if (cite) emit('citation-click', cite)
}

const copied = ref(false)
/** 复制对勾 2.5s 后自熄 */
let copyTimer: ReturnType<typeof setTimeout> | undefined

async function copyContent() {
  const text = props.isStreaming && props.streamContent !== undefined ? props.streamContent : props.message.content
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 2500)
  } catch { /* fallback */ }
}

// ── 流式逐字「晕开」 ──
//
// 正文用 v-html 每次整体替换 innerHTML，所有节点都是新的 —— 如果给整段都加
// 入场动画，每次重渲染都会重播一遍（就是之前引用标记闪烁的同一个坑）。
// 所以只在**本次新增的那几个字**上挂动画：下一 tick 它们会被替换成普通文本，
// 不会再重播。
const bodyRef = ref<HTMLElement | null>(null)
let prevTextLen = 0

watch(renderedContent, async () => {
  if (!props.isStreaming) { prevTextLen = 0; return }
  await nextTick()
  const el = bodyRef.value
  if (!el) return
  const total = el.textContent?.length ?? 0
  if (total > prevTextLen) animateTail(el, prevTextLen, total)
  prevTextLen = total
})

function animateTail(el: HTMLElement, from: number, to: number) {
  const need0 = to - from
  if (need0 <= 0) return

  // 只取尾部文本节点，避免每次遍历整棵子树
  const texts: Text[] = []
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let node: Node | null
  while ((node = walker.nextNode())) texts.push(node as Text)

  let need = need0
  for (let i = texts.length - 1; i >= 0 && need > 0; i--) {
    const tn = texts[i]
    const value = tn.nodeValue ?? ''
    if (!value) continue
    const take = Math.min(need, value.length)
    const cut = value.length - take
    const tail = value.slice(cut)

    const frag = document.createDocumentFragment()
    let idx = 0
    for (const ch of tail) {
      const span = document.createElement('span')
      span.className = 'char-in'
      // 相邻字错开 12ms：与 90ms 的单字动画配合，6 个字 150ms 内跑完，
      // 不会被下一次重渲染截断（30ms 会拖到 240ms）
      span.style.animationDelay = `${idx * 12}ms`
      span.textContent = ch
      frag.appendChild(span)
      idx++
    }
    tn.nodeValue = value.slice(0, cut)
    tn.parentNode?.insertBefore(frag, tn.nextSibling)
    need -= take
  }
}

const hasRagSteps = computed(() => {
  const steps = props.message.ragSteps
  return steps && Object.values(steps).some((s) => s !== undefined)
})

const stepCount = computed(() => Object.values(props.message.ragSteps ?? {}).filter(Boolean).length)

/**
 * 步骤区标题。
 *
 * 意图判定为库外（寒暄/元问题）时后端走「直答」分支，只有 intent + answer 两步，
 * 这时再写「检索与推理过程」会误导 —— 根本没检索。
 */
const stepsTitle = computed(() => {
  const hasRetrieval = Boolean(props.message.ragSteps?.retrieval)
  return `${hasRetrieval ? '检索与推理过程' : '推理过程'} · ${stepCount.value} 步`
})

const isProcessing = computed(() => {
  const steps = props.message.ragSteps
  if (!steps) return false
  return Object.values(steps).some((s) => s?.status === 'pending')
})

// ── 待答提示：时间尺度 + 实时计数 + 逐字 ──
//
// 以前这里是 5 句文案每 2.2 秒**随机**轮换，跟实际执行到哪一步毫无关系。
// 现在：
//   - 步骤准确：取 `ragSteps` 里 pending 的那一步
//   - 混合检索 / 融合重排 优先显示**真实计数**（后端 live 进度帧），拿不到就退化
//   - 文案按该步已耗时递进（时间尺度），不是固定一句
//   - 文字逐字出现（90ms/字、blur 6px→0），比静态文字有生命感
//
// 计时器只在「当前步骤在跑」时开，100ms 一跳用于刷新已耗时；
// 用 100ms 而不是 16ms（rAF）——耗时显示只到 0.1s 精度，没必要每帧重建 VDOM。

const runningStep = computed(() => currentRunningStep(props.message.ragSteps))
const stepElapsedMs = ref(0)
let elapsedTimer: ReturnType<typeof setInterval> | undefined
let stepStartAt = 0
let lastStepKey: string | null = null

watch(
  [runningStep, () => props.isStreaming],
  ([key, streaming]) => {
    if (key && streaming) {
      // 切到新步骤才重置起点；同一步内持续计时
      if (key !== lastStepKey) {
        lastStepKey = key
        stepStartAt = Date.now()
        stepElapsedMs.value = 0
      }
      if (!elapsedTimer) {
        elapsedTimer = setInterval(() => {
          stepElapsedMs.value = Date.now() - stepStartAt
        }, 100)
      }
    } else {
      if (elapsedTimer) {
        clearInterval(elapsedTimer)
        elapsedTimer = undefined
      }
      lastStepKey = null
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
})

/** 该步最新的 metrics（live 进度或完成态都可能是） */
const runningMetrics = computed(() => {
  const steps = props.message.ragSteps
  const key = runningStep.value
  if (!steps || !key) return undefined
  return (steps as Record<string, { metrics?: unknown } | undefined>)[key]?.metrics as
    | Record<string, unknown>
    | undefined
})

/** 当前提示：文案模板 + 计数 + 签名 */
const hint = computed<StepHint | null>(() => {
  const key = runningStep.value
  if (!key) return null
  return stepHint(key, stepElapsedMs.value, runningMetrics.value)
})

/**
 * 逐字渲染的分片。
 *
 * 含计数时把 `{n}` 拆出去单独渲染成徽标 —— 这样数字变化不会重放整句的逐字动画
 * （签名不变就不重建，见模板里的 `:key`）。
 */
const hintParts = computed<Array<{ type: 'text' | 'count'; value: string | number }>>(() => {
  const h = hint.value
  if (!h) return []
  if (h.count == null) return [{ type: 'text', value: h.text }]
  const segs = splitCountTemplate(h.text)
  const out: Array<{ type: 'text' | 'count'; value: string | number }> = []
  segs.forEach((seg, i) => {
    if (seg) out.push({ type: 'text', value: seg })
    if (i < segs.length - 1) out.push({ type: 'count', value: h.count as number })
  })
  return out
})

/** 逐字动画的 key：只随「文案结构」变化，不随数字变化 */
const hintKey = computed(() => hint.value?.text ?? '')

// ── 步骤展开 ──

// 默认展开：步骤是逐个长出来的，收起来就看不到"渐进"的观感
const stepsOpen = ref(true)
</script>

<template>
  <div class="group/turn flex gap-3.5 py-4">
    <!-- AI 标记 -->
    <div class="shrink-0 pt-0.5">
      <div
        class="grid h-[26px] w-[26px] place-items-center rounded-full text-white shadow-[0_2px_8px_rgba(66,133,244,.3)]"
        style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.4l1.9 5.1 5.1 1.9-5.1 1.9L12 16.4l-1.9-5.1L5 9.4l5.1-1.9z" /></svg>
      </div>
    </div>

    <div class="min-w-0 flex-1">
      <!-- RAG 步骤（可折叠） -->
      <div v-if="hasRagSteps" class="mb-3.5 overflow-hidden rounded-lg border border-line bg-surface-2">
        <button
          class="flex w-full items-center gap-2 px-3 py-2.5 text-[12.5px] text-muted transition-colors hover:bg-surface"
          @click="stepsOpen = !stepsOpen"
        >
          <svg v-if="!isProcessing" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2.4l1.9 5.1 5.1 1.9-5.1 1.9L12 16.4l-1.9-5.1L5 9.4l5.1-1.9z" /></svg>
          <span v-else class="h-3 w-3 animate-spin rounded-full border-[1.5px] border-accent border-t-transparent" />

          <!-- 待答提示：逐字出现 + 计数徽标（数字单独成块，不重放整句动画） -->
          <span v-if="isProcessing" class="hint-text font-medium text-accent-text">
            <template v-for="(part, pi) in hintParts" :key="hintKey + ':' + pi">
              <template v-if="part.type === 'text'">
                <span
                  v-for="(ch, ci) in String(part.value)"
                  :key="pi + '-' + ci"
                  class="char-in"
                  :style="{ animationDelay: ci * 22 + 'ms' }"
                >{{ ch }}</span>
              </template>
              <span v-else class="hint-count">{{ part.value }}</span>
            </template>
          </span>
          <span v-else>{{ stepsTitle }}</span>

          <ChevronDown
            :size="13"
            class="ml-auto transition-transform"
            :class="{ 'rotate-180': stepsOpen }"
          />
        </button>
        <div
          class="grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(.215,.61,.355,1)]"
          :style="{ gridTemplateRows: stepsOpen ? '1fr' : '0fr' }"
        >
          <div class="overflow-hidden">
            <div class="border-t border-line px-3 pb-2 pt-1">
              <RagPipelineSimple :steps="message.ragSteps!" />
            </div>
          </div>
        </div>
      </div>

      <!-- 正文 -->
      <div
        v-if="renderedContent"
        ref="bodyRef"
        class="markdown-body"
        :class="{ 'is-streaming': isStreaming }"
        v-html="renderedContent"
        @click="handleContentClick"
      />

      <!-- 等待首个 token -->
      <div v-else-if="isStreaming" class="flex items-center gap-1.5 py-2">
        <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" style="animation-delay: 0ms" />
        <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" style="animation-delay: 150ms" />
        <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" style="animation-delay: 300ms" />
      </div>

      <!-- 操作栏 -->
      <div
        v-if="!isStreaming && message.content"
        class="mt-3 flex items-center gap-0.5 opacity-0 transition-opacity group-hover/turn:opacity-100"
      >
        <button class="inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] text-muted transition-colors hover:bg-surface hover:text-ink" @click="copyContent">
          <Check v-if="copied" :size="12" class="text-ok" />
          <Copy v-else :size="12" />
          复制
        </button>
        <button
          v-if="canRegenerate"
          class="inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] text-muted transition-colors hover:bg-surface hover:text-ink"
          title="用同一个问题重新回答（旧回答会被替换）"
          @click="emit('regenerate')"
        >
          <RotateCw :size="12" />
          重新生成
        </button>
        <button class="inline-flex h-7 items-center justify-center rounded-full px-2.5 text-muted transition-colors hover:bg-surface hover:text-ink" title="有帮助">
          <ThumbsUp :size="12" />
        </button>

        <button
          v-if="message.citations?.length"
          class="ml-auto inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] text-muted transition-colors hover:bg-surface hover:text-ink"
          @click="emit('show-citation-list')"
        >
          <BookOpen :size="12" />
          参考文献 {{ message.citations.length }}
        </button>
      </div>

      <!-- 错误 -->
      <div
        v-if="chatStore.streamError"
        class="mt-3 flex items-start gap-2 rounded-lg border border-line bg-danger-soft px-3 py-2"
      >
        <AlertCircle :size="13" class="mt-0.5 shrink-0 text-danger" />
        <p class="text-[12px] leading-relaxed text-danger">{{ chatStore.streamError }}</p>
      </div>
    </div>
  </div>
</template>
