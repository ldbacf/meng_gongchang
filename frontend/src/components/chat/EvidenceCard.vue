<script setup lang="ts">
import type { EvidenceResponse } from '@/api/citation'
import { computed, ref, watch } from 'vue'
import { Loader2 } from 'lucide-vue-next'

/**
 * 证据卡 —— 用户点引用后，右栏先展示「这篇文献说了什么」，
 * PDF 降为末位入口（"查看原文"）。
 *
 * ## 为什么不是直接开 PDF
 *
 * 本机 MinIO 走 Windows bind mount，实测 240 KB/s：一份 2.76 MB 的 PDF
 * 整份拉完要 11.7 秒。用户点个引用等十几秒才看到第一页，体验是断的。
 * 而摘要、样本量、命中章节这些数据随 `/evidence` 一次返回（毫秒级），
 * 足够回答"这篇文章支持这个结论吗"。
 *
 * ## 读者的动线：先看被引的那段，再看这是一篇什么文章
 *
 * 用户点 [2] 想确认的是「[2] 这句引用到底出自哪里、原文怎么说的」，
 * 所以**被引原文排在最前**（「引用原文」），文献出处与摘要退到它后面。
 * 早先的版本把标题、作者、核心结论、摘要、原文片段依次堆下来，
 * 被引的那段正文排在屏幕第 700 多像素处，得滚一屏才看见 ——
 * 读者反馈的"信息很多但都不对"就是这个顺序造成的。
 *
 * ## 上下文只画「逻辑」，不铺成一锅粥
 *
 * 早期实现把前一块、命中块、后一块不分主次地连排，命中块只加深一点底色。
 * 结果是一屏连续文字里读者分不清哪句是被引的 —— 上下文反而成了噪音。
 * 现在：
 *   - 默认**只显示命中块**，且明确标注「被引原文」
 *   - 点「显示上下文」才展开前后块，并各带一行 `上文 · <章节>` / `下文 · <章节>`，
 *     让读者知道这块和命中块是什么关系（同一节还是上一节）
 *
 * ## 只给读者看该看的东西
 *
 * 这里踩过一次真实的坑：初版把数据来源也印在界面上（`doc-meta · abstract_cn`、
 * `ES chunks · L1`、`doc_id=`），还为了塞进窄栏把正文压到 12.5–13px。
 * 结果是**信息很挤，但都不是读者要的信息**。
 *
 * 现在的规矩：
 *   - 界面文字只出现文献本身的信息（标题/作者/期刊/摘要/正文）
 *   - 实现细节（字段名、桶名、chunk 层级、doc_id）一律不渲染
 *   - 正文 15px / 行高 1.95，先保证能读，再考虑一屏能放多少
 *
 * ## 缺字段时诚实降级，但**不编结论**
 *
 * 无结构式摘要（指南与综述常见）时不伪造结论段：
 * 没有 `结论` 段就整个不渲染「核心结论」，而不是拿正文首句冒充 ——
 * 正文首句就在下面的「引用原文」里，冒充一次等于同一段话印两遍，
 * 还让读者以为那是作者的结论。
 *
 * ## 卡片里不放「查看原文 / 复制原文」
 *
 * 面板标题栏右上角已经有「原文」按钮，卡片底部再放一个「查看原文」是
 * 同一个动作出现两次；「复制原文」当时挂的 `@copy` 在父组件里是
 * `() => {}` —— 点了没有任何效果，纯粹是骗人的按钮。正文本来就可用
 * 鼠标选中，需要复制时读者自己会选。所以这两个都不留。
 */
const props = defineProps<{
  evidence: EvidenceResponse | null
  loading: boolean
  /**
   * 引用片段本身（`citation.snippet`）。
   *
   * 后端返回的 `hit_paragraphs` 是**整个 chunk**，而 snippet 只是它的前 200 字。
   * 8285 那一块的 chunk 有 11 段（2.13 合并了 2.13.1–2.13.5），原样铺出来
   * 就是一屏看不到头的正文墙 —— 读者反而找不到"引用的到底是哪句"。
   * 所以用 snippet 圈出开头被引的那几段，其余折进「本节其余」。
   */
  snippet?: string
}>()

const abstractOpen = ref(false)
const contextOpen = ref(false)
const passageOpen = ref(false)

/** 换了一篇文献就把展开状态收回去，否则上一条的展开会带过来 */
watch(
  () => props.evidence?.doc_id,
  () => {
    abstractOpen.value = false
    contextOpen.value = false
    passageOpen.value = false
  },
)

/** 结构式摘要为空 → 该文只有单段叙述式摘要 */
const hasSections = computed(
  () => (props.evidence?.abstract_sections?.length ?? 0) > 0,
)

/** 结论段：只在摘要真的分了「结论」时才有，没有就是空串（模板据此整块隐藏） */
const conclusionText = computed(() => {
  const sections = props.evidence?.abstract_sections ?? []
  return sections.find((s) => s.key === '结论')?.text ?? ''
})

/** 非结论段的其余分段，按期刊顺序（背景/目的/方法/结果） */
const otherSections = computed(() =>
  (props.evidence?.abstract_sections ?? []).filter((s) => s.key !== '结论'),
)

const sampleLabel = computed(() => {
  const s = props.evidence?.sample_size
  if (!s) return ''
  // 「纳入 18 篇」是文献数量，不能标成样本量
  if (!s.is_subject_count) return `纳入 ${s.value} ${s.unit}`
  return `样本量 ${s.value.toLocaleString()} ${s.unit}`
})

/** 类型着色：指南 / Meta / 论著 / 综述 各有区分 */
const typeClass = computed(() => {
  const t = props.evidence?.article_type ?? ''
  if (/指南|共识|规范|标准/.test(t)) return 'is-guide'
  if (/循证|Meta/i.test(t)) return 'is-meta'
  if (/综述|述评|笔谈/.test(t)) return 'is-review'
  return 'is-study'
})

const passage = computed(() => props.evidence?.passage ?? null)

/** 命中位置的章节路径 —— 这是读者的定位信息，保留 */
const hitHeading = computed(() => passage.value?.hit_heading ?? '')

const hitParagraphs = computed(() => passage.value?.hit_paragraphs ?? [])

/** 去标点/空白后比较，前端只用来判边界，不做任何展示 */
function normForMatch(s: string): string {
  return s.replace(/[\s，。、；：！？…—－·,.;:!?'"“”‘’（）()《》〈〉【】[\]]+/g, '')
}

/**
 * 命中块按「被引的那几段」与「本节其余」切开。
 *
 * 后端给的 `hit_paragraphs` 是**整个 chunk**：8285 的 2.13 一节合并了
 * 2.13.1–2.13.5，共 11 段；而 `citation.snippet` 只截了它的前 200 字。
 * 原样铺开就是一屏望不到头的正文，读者反而找不到引用落在哪一句。
 *
 * 所以按 snippet 的长度去数「前几段合起来够长」，超出的部分折进
 * 「本节其余 N 段」。数不准时也只是多折/少折一段，不会漏掉正文。
 */
const hitSplit = computed(() => {
  const paras = hitParagraphs.value
  // 本来就不长的块不必拆
  if (paras.length <= 3) return { lead: paras, rest: [] as string[] }

  const target = normForMatch(props.snippet ?? '')
  let n = target ? 0 : 3
  if (target) {
    let acc = ''
    for (const p of paras) {
      acc += normForMatch(p)
      n += 1
      if (acc.length >= target.length) break
    }
  }
  // 至少 1 段、至多留 1 段给「其余」，避免出现「其余 0 段」的空控件
  const cut = Math.max(1, Math.min(n, paras.length - 1))
  return { lead: paras.slice(0, cut), rest: paras.slice(cut) }
})

const restCount = computed(() => hitSplit.value.rest.length)

const canToggleContext = computed(
  () => !!(passage.value?.has_prev || passage.value?.has_next),
)

/**
 * 前后块的标签只取章节路径末段。
 *
 * `prev_heading` 是完整路径（`2 认识高血压 → 2.12 … → 2.12.2 戒烟技巧`），
 * 整条印在上下文里比正文还长。读者只需要知道"这是 2.12.2 那段"。
 */
function lastSegment(path: string): string {
  if (!path) return ''
  const parts = path.split('→')
  return parts[parts.length - 1].trim()
}

/** 与命中块同节时不必重复章节名，标点位置即可 */
const prevLabel = computed(() => {
  const p = passage.value
  if (!p?.has_prev) return ''
  const name = lastSegment(p.prev_heading)
  return name && p.prev_heading !== p.hit_heading ? `上文 · ${name}` : '上文'
})

const nextLabel = computed(() => {
  const p = passage.value
  if (!p?.has_next) return ''
  const name = lastSegment(p.next_heading)
  return name && p.next_heading !== p.hit_heading ? `下文 · ${name}` : '下文'
})

function toggleAbstract() {
  abstractOpen.value = !abstractOpen.value
}

function toggleContext() {
  contextOpen.value = !contextOpen.value
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- 加载态 -->
    <div v-if="loading" class="flex flex-1 items-center justify-center gap-2">
      <Loader2 :size="16" class="animate-spin text-accent" />
      <span class="text-[13px] text-muted">加载文献信息…</span>
    </div>

    <!-- 空态 -->
    <div
      v-else-if="!evidence"
      class="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-faint"
    >
      暂无该文献的详细信息
    </div>

    <!-- 正文 -->
    <div v-else class="ev-scroll flex-1 overflow-y-auto px-6 py-6">
      <!-- ── 被引原文（读者点引用就是来看这个，排最前） ── -->
      <section v-if="passage" class="ev-first">
        <h4 class="ev-h">引用原文</h4>

        <p v-if="hitHeading" class="ev-locate">{{ hitHeading }}</p>

        <div class="ev-hit-group">
          <p v-for="(para, i) in hitSplit.lead" :key="i" class="ev-para">
            {{ para }}
          </p>

          <!-- 一节被 chunk 合并了多段时，只铺开被引的那几段，其余折起来 -->
          <template v-if="restCount">
            <div v-if="passageOpen" class="ev-rest">
              <p v-for="(para, i) in hitSplit.rest" :key="i" class="ev-para">
                {{ para }}
              </p>
            </div>
            <button class="ev-more" @click="passageOpen = !passageOpen">
              {{
                passageOpen
                  ? '收起本节其余内容'
                  : `展开本节其余 ${restCount} 段`
              }}
            </button>
          </template>
        </div>

        <!-- 上下文默认收起：一屏连续文字里读者分不清哪句是被引的 -->
        <template v-if="canToggleContext">
          <button class="ev-more" @click="toggleContext">
            {{ contextOpen ? '收起上下文' : '显示上下文' }}
          </button>

          <div v-if="contextOpen" class="ev-ctx">
            <div v-if="passage.has_prev" class="ev-ctx-block">
              <p class="ev-ctx-label">{{ prevLabel }}</p>
              <p class="ev-para">{{ passage.prev_text }}</p>
            </div>
            <div v-if="passage.has_next" class="ev-ctx-block">
              <p class="ev-ctx-label">{{ nextLabel }}</p>
              <p class="ev-para">{{ passage.next_text }}</p>
            </div>
          </div>
        </template>
      </section>

      <!-- 未定位到命中章节：说明原因，但不挡后面的摘要 -->
      <p v-else-if="evidence.message" class="ev-note">{{ evidence.message }}</p>

      <!-- ── 出处 ── -->
      <header class="ev-head" :class="{ 'has-first': !!passage }">
        <h3 class="ev-title">{{ evidence.title || '未知标题' }}</h3>
        <p v-if="evidence.authors" class="ev-authors">{{ evidence.authors }}</p>
        <p class="ev-source">
          <span class="ev-year">{{ evidence.year }}</span>
          <template v-if="evidence.journal"> · {{ evidence.journal }}</template>
          <template v-if="evidence.article_type">
            ·
            <span class="ev-type" :class="typeClass">{{ evidence.article_type }}</span>
          </template>
        </p>
        <!-- 只有真实有值的字段才出现 -->
        <p v-if="sampleLabel" class="ev-sample">{{ sampleLabel }}</p>
      </header>

      <!-- ── 核心结论（只有摘要真的分了「结论」段才出现） ── -->
      <section v-if="conclusionText" class="ev-sec">
        <h4 class="ev-h">核心结论</h4>
        <blockquote class="ev-quote">{{ conclusionText }}</blockquote>
      </section>

      <!-- ── 摘要 ──
           两种形态都要能折叠：有分段时逐段列出，无分段时整段列出。
           早期实现只在「有分段」时给展开按钮，指南/综述这类无分段摘要
           会把整屏撑满。 -->
      <section v-if="evidence.abstract_raw" class="ev-sec">
        <h4 class="ev-h">
          摘要
          <button class="ev-toggle" @click="toggleAbstract">
            {{ abstractOpen ? '收起' : '展开' }}
          </button>
        </h4>

        <div
          v-if="hasSections"
          class="ev-abstract"
          :class="{ 'is-clamped': !abstractOpen }"
        >
          <p v-for="s in otherSections" :key="s.key" class="ev-para">
            <span class="ev-abstract-key">{{ s.key }}</span>{{ s.text }}
          </p>
        </div>
        <p v-else class="ev-abstract" :class="{ 'is-clamped': !abstractOpen }">
          {{ evidence.abstract_raw }}
        </p>
      </section>

      <!-- DOI 单独放最后：读者要引用时才需要，不参与阅读动线 -->
      <p v-if="evidence.doi" class="ev-doi">DOI {{ evidence.doi }}</p>
    </div>
  </div>
</template>

<style scoped>
/* 颜色全部走 tokens.css 的语义变量，暗色模式只改变量、不改这里。 */

/* ── 被引原文 ── */
.ev-first {
  margin-bottom: 24px;
}
.ev-hit-group {
  padding: 12px 15px;
  border-radius: 10px;
  /* 浅底 + 左侧 accent 竖线：读者一眼能看出「这一段是被引的」，
     又不至于像整块蓝板那样把正文糊住（真实截图确认过）。 */
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  border-left: 2px solid var(--accent);
  border-radius: 0 10px 10px 0;
  font-size: 15px;
  line-height: 1.95;
  color: var(--text);
}

.ev-more {
  margin-top: 10px;
  padding: 0;
  font-size: 12.5px;
  color: var(--accent-text);
  background: none;
  border: 0;
  cursor: pointer;
}
.ev-more:hover {
  text-decoration: underline;
}
/* 折叠按钮在命中块内部时，跟着块的左内边距走 */
.ev-hit-group .ev-more {
  margin-top: 12px;
}
.ev-rest .ev-para {
  margin-bottom: 11px;
}
.ev-rest {
  margin-top: 11px;
}

.ev-ctx {
  margin-top: 14px;
  padding-left: 15px;
  border-left: 1px solid var(--border);
}
.ev-ctx-block + .ev-ctx-block {
  margin-top: 14px;
}
.ev-ctx-label {
  margin-bottom: 5px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--faint);
}
.ev-ctx .ev-para {
  font-size: 14px;
  line-height: 1.95;
  color: var(--muted);
}

.ev-locate {
  margin-bottom: 9px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--accent-text);
}

.ev-note {
  margin-bottom: 20px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--warn);
}

/* ── 出处 ── */
.ev-head.has-first {
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.ev-title {
  margin-bottom: 7px;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.6;
  letter-spacing: -0.1px;
  color: var(--text);
}
.ev-authors {
  margin-bottom: 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--muted);
}
.ev-source {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--faint);
}
.ev-year {
  font-weight: 600;
  color: var(--muted);
}
.ev-type {
  font-weight: 500;
}
.ev-type.is-guide,
.ev-type.is-meta {
  color: var(--accent-text);
}
.ev-type.is-study {
  color: var(--ok);
}
.ev-type.is-review {
  color: var(--warn);
}
.ev-sample {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--muted);
}

/* ── 小节标题 ──
 * 不用 uppercase、不用等宽字体、不加数据来源注脚 ——
 * 那些是内部术语，读者只需要知道「这一段是什么」。
 */
.ev-sec {
  margin-top: 24px;
}
.ev-h {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
}
.ev-toggle {
  margin-left: auto;
  font-size: 12.5px;
  font-weight: 400;
  color: var(--accent-text);
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
}
.ev-toggle:hover {
  text-decoration: underline;
}

/* ── 结论 ── */
.ev-quote {
  padding: 12px 15px;
  border-left: 2px solid var(--accent);
  border-radius: 0 10px 10px 0;
  background: var(--bg);
  font-size: 15px;
  line-height: 1.95;
  color: var(--text-2);
}

/* ── 摘要与正文共用排版：15px / 行高 1.95 ── */
.ev-abstract {
  font-size: 15px;
  line-height: 1.95;
  color: var(--text-2);
}
.ev-abstract.is-clamped {
  max-height: 5.85em; /* 3 行：字号 15 × 行高 1.95 */
  overflow: hidden;
  mask-image: linear-gradient(0deg, #000 52%, transparent);
  -webkit-mask-image: linear-gradient(0deg, #000 52%, transparent);
}
.ev-para {
  margin: 0 0 11px;
}
.ev-para:last-child {
  margin-bottom: 0;
}
.ev-abstract-key {
  display: inline-block;
  min-width: 36px;
  margin-right: 8px;
  font-weight: 600;
  color: var(--accent-text);
}

/* ── 页脚 ── */
.ev-doi {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.6;
  color: var(--faint);
  word-break: break-all;
}

/* 滚动条：窄栏里默认样式太粗 */
.ev-scroll::-webkit-scrollbar {
  width: 8px;
}
.ev-scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 4px;
  border: 2px solid var(--bg);
}
</style>
