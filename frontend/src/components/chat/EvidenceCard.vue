<script setup lang="ts">
import type { EvidenceResponse } from '@/api/citation'
import { computed, ref } from 'vue'
import { FileText, Loader2 } from 'lucide-vue-next'

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
 * ## 排版原则：连续文本，不是方块拼接
 *
 * 上下文刻意渲染成**一段连续的话**（上文 → 命中 → 下文），而不是三个
 * 带边框的独立 block。原文本来就是连续的，只是被 chunk 边界切开了；
 * 拆成方块会让读者自己做心理拼接。命中段落用淡色背景铺满行宽，
 * `box-decoration-break: clone` 保证换行处底色不断。
 *
 * ## 缺字段时诚实降级
 *
 * - 无结构式摘要（1248 篇中 337 篇）→ 不用伪造的「结论」，改用命中段落首句，
 *   并明确标注「本文摘要无结论段」
 * - 抽不到样本量 / 抽到的是文献篇数 → 该标签不渲染，而不是显示 0 或错标
 * - 无证据等级字段（全库都没有）→ 绝不显示
 */
const props = defineProps<{
  evidence: EvidenceResponse | null
  loading: boolean
  /** 展示 PDF 的动作由父组件决定（面板里是切换视图，测试里是 spy） */
  pdfAvailable: boolean
}>()

const emit = defineEmits<{
  openPdf: []
  copy: [text: string]
}>()

const abstractOpen = ref(false)
const passageOnlyHit = ref(false)

/** 结构式摘要为空 → 该文只有单段叙述式摘要 */
const hasSections = computed(
  () => (props.evidence?.abstract_sections?.length ?? 0) > 0,
)

/**
 * 结论句。
 *
 * 优先取结构式摘要的「结论」段；没有就退回最后一个有内容的段
 * （「结果」段通常也能说明问题）。两者都没有时返回空串，
 * 由模板显示降级提示 —— 不编造。
 */
const conclusionText = computed(() => {
  const sections = props.evidence?.abstract_sections ?? []
  const conclusion = sections.find((s) => s.key === '结论')
  if (conclusion?.text) return conclusion.text
  return ''
})

/** 非结论段的其余分段，按期刊顺序（背景/目的/方法/结果） */
const otherSections = computed(() =>
  (props.evidence?.abstract_sections ?? []).filter((s) => s.key !== '结论'),
)

/**
 * 降级用的「核心句」：命中段落的第一段。
 *
 * 只在没有结论段时使用，且模板里会明确标注来源 —— 让用户知道
 * 这句话不是作者写的结论，而是我们挑出来的正文片段。
 */
const fallbackSentence = computed(() => {
  const first = props.evidence?.passage?.hit_paragraphs?.[0] ?? ''
  if (!first) return ''
  // 截到第一个句末标点，避免把整段贴上来
  const m = first.match(/^[^。！？；]+[。！？；]?/)
  return (m ? m[0] : first).trim()
})

const sampleLabel = computed(() => {
  const s = props.evidence?.sample_size
  if (!s) return ''
  // 「纳入 18 篇」是文献数量，不能标成样本量
  if (!s.is_subject_count) return `纳入 ${s.value} ${s.unit}`
  return `样本量 ${s.value.toLocaleString()} ${s.unit}`
})

/** 类型徽章配色：指南 / Meta / 论著 / 综述 各有区分 */
const typeClass = computed(() => {
  const t = props.evidence?.article_type ?? ''
  if (/指南|共识|规范|标准/.test(t)) return 'badge-guide'
  if (/循证|Meta/i.test(t)) return 'badge-meta'
  if (/综述|述评|笔谈/.test(t)) return 'badge-review'
  return 'badge-study'
})

const passage = computed(() => props.evidence?.passage ?? null)

function toggleAbstract() {
  abstractOpen.value = !abstractOpen.value
}

function toggleOnlyHit() {
  passageOnlyHit.value = !passageOnlyHit.value
}

function copyConclusion() {
  const text = conclusionText.value || fallbackSentence.value
  if (text) emit('copy', text)
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- 加载态 -->
    <div v-if="loading" class="flex flex-1 items-center justify-center gap-2">
      <Loader2 :size="16" class="animate-spin text-accent" />
      <span class="text-[12.5px] text-muted">加载文献信息…</span>
    </div>

    <!-- 空态 -->
    <div
      v-else-if="!evidence"
      class="flex flex-1 items-center justify-center px-6 text-center text-[12.5px] text-faint"
    >
      暂无该文献的详细信息
    </div>

    <!-- 正文 -->
    <div v-else class="flex-1 overflow-y-auto px-4 py-4">
      <!-- 标题与元信息 -->
      <h3 class="mb-1.5 text-[14px] font-semibold leading-snug text-ink">
        {{ evidence.title || '未知标题' }}
      </h3>
      <p v-if="evidence.authors" class="mb-1 text-[12px] leading-relaxed text-muted">
        {{ evidence.authors }}
      </p>
      <p class="text-[11.5px] text-faint">
        <span class="font-medium text-muted">{{ evidence.year }}</span>
        <template v-if="evidence.journal"> · {{ evidence.journal }}</template>
        <template v-if="evidence.source"> · {{ evidence.source }}</template>
      </p>

      <!-- 标签行：只渲染真实有值的字段 -->
      <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span v-if="evidence.article_type" class="ev-badge" :class="typeClass">
          {{ evidence.article_type }}
        </span>
        <span v-if="sampleLabel" class="ev-badge">{{ sampleLabel }}</span>
        <span v-if="hasSections" class="ev-badge badge-ok">结构式摘要</span>
        <span v-else class="ev-badge badge-weak">无结论段</span>
      </div>

      <!-- ── 核心结论 ── -->
      <section class="mt-4">
        <h4 class="ev-section-title">
          核心结论
          <span v-if="!conclusionText" class="ev-section-note">
            取自正文 {{ passage?.hit_heading || '命中章节' }}
          </span>
          <span v-else class="ev-section-note">abstract_cn · 结论</span>
        </h4>
        <blockquote v-if="conclusionText" class="ev-quote">
          {{ conclusionText }}
        </blockquote>
        <blockquote v-else-if="fallbackSentence" class="ev-quote ev-quote-fallback">
          {{ fallbackSentence }}
          <span class="ev-fallback-note">
            本文摘要没有「结论」段（指南与综述常见，全库 1248 篇中 337 篇如此），
            此处引用的是命中正文的核心句，不是作者写的结论。
          </span>
        </blockquote>
        <p v-else class="text-[12px] text-faint">该文献无可提取的结论句。</p>
      </section>

      <!-- ── 摘要 ── -->
      <section v-if="evidence.abstract_raw" class="mt-4">
        <h4 class="ev-section-title">
          摘要
          <span class="ev-section-note">doc-meta · abstract_cn</span>
          <button v-if="hasSections" class="ev-toggle" @click="toggleAbstract">
            {{ abstractOpen ? '收起' : '展开' }}
          </button>
        </h4>

        <div v-if="hasSections" class="ev-abstract" :class="{ 'ev-clamped': !abstractOpen }">
          <p v-for="s in otherSections" :key="s.key" class="mb-2 last:mb-0">
            <span class="ev-abstract-key">{{ s.key }}</span>{{ s.text }}
          </p>
        </div>
        <p v-else class="ev-abstract">{{ evidence.abstract_raw }}</p>
      </section>

      <!-- ── 连续上下文 ── -->
      <section v-if="passage" class="mt-4">
        <h4 class="ev-section-title">
          正文上下文
          <span class="ev-section-note">上文 + 命中块 + 下文</span>
          <button
            v-if="passage.has_prev || passage.has_next"
            class="ev-toggle"
            @click="toggleOnlyHit"
          >
            {{ passageOnlyHit ? '显示前后文' : '只看命中' }}
          </button>
        </h4>

        <div class="ev-passage" :class="{ 'only-hit': passageOnlyHit }">
          <!-- 上文 -->
          <template v-if="passage.has_prev">
            <div class="ev-passage-mark is-nb">
              <span class="ev-passage-lbl">上文</span>{{ passage.prev_heading }}
            </div>
            <p class="ev-passage-nb is-top">……{{ passage.prev_text }}</p>
          </template>

          <!-- 命中 -->
          <div class="ev-passage-mark">
            <span class="ev-passage-lbl">命中</span>{{ passage.hit_heading }}
          </div>
          <div class="ev-passage-hit-group">
            <p v-for="(para, i) in passage.hit_paragraphs" :key="i" class="ev-passage-hit-line">
              <span class="ev-passage-hit">{{ para }}</span>
            </p>
          </div>

          <!-- 下文 -->
          <template v-if="passage.has_next">
            <div class="ev-passage-mark is-nb">
              <span class="ev-passage-lbl">下文</span>{{ passage.next_heading }}
            </div>
            <p class="ev-passage-nb is-bot">{{ passage.next_text }}……</p>
          </template>
        </div>
      </section>

      <!-- 未定位到命中章节时的说明（不阻断阅读） -->
      <p v-else-if="evidence.message" class="mt-4 text-[11.5px] text-warn">
        {{ evidence.message }}
      </p>

      <!-- 标识 -->
      <section class="mt-4 border-t border-line pt-3">
        <p class="font-mono text-[10.5px] leading-relaxed text-faint">
          doc_id={{ evidence.doc_id }}
          <template v-if="evidence.doi"><br />doi={{ evidence.doi }}</template>
        </p>
      </section>

      <!-- 动作 -->
      <div class="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        <button v-if="pdfAvailable" class="ev-btn" @click="emit('openPdf')">
          <FileText :size="12" />
          查看原文 PDF
        </button>
        <button
          v-if="conclusionText || fallbackSentence"
          class="ev-btn"
          @click="copyConclusion"
        >
          复制结论
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 全部颜色走 tokens.css 的语义变量（--accent / --border / --text…），
   不写死色值 —— 暗色模式只改变量、不改这里。 */
.ev-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 500;
  background: var(--surface);
  color: var(--muted);
}
.badge-guide {
  background: var(--accent-soft);
  color: var(--accent-text);
}
.badge-meta {
  background: var(--accent-soft);
  color: var(--accent-text);
  opacity: 0.92;
}
.badge-study {
  background: var(--ok-soft);
  color: var(--ok);
}
.badge-review {
  background: var(--warn-soft);
  color: var(--warn);
}
.badge-ok {
  background: var(--ok-soft);
  color: var(--ok);
}
/* 虚线框：明确表示「这个字段缺失」，与有值的实心徽章区分开 */
.badge-weak {
  background: transparent;
  border: 1px dashed var(--border-strong);
  color: var(--faint);
}

.ev-section-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.45px;
  text-transform: uppercase;
  color: var(--faint);
}
.ev-section-note {
  font-size: 9.5px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  font-family: var(--font-mono);
  color: var(--faint);
  opacity: 0.85;
}
.ev-toggle {
  margin-left: auto;
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--accent-text);
  cursor: pointer;
  background: none;
  border: 0;
  padding: 0;
}
.ev-toggle:hover {
  text-decoration: underline;
}

/* 结论引用块 */
.ev-quote {
  padding: 10px 12px;
  border-left: 2px solid var(--accent);
  border-radius: 0 8px 8px 0;
  background: var(--bg);
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--text-2);
}
/* 降级态用警示色，视觉上就能看出「这不是原文结论」 */
.ev-quote-fallback {
  border-left-color: var(--warn);
}
.ev-fallback-note {
  display: block;
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px dashed var(--border);
  font-size: 11px;
  line-height: 1.7;
  color: var(--faint);
}

/* 摘要 */
.ev-abstract {
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--text-2);
}
.ev-clamped {
  max-height: 5.6em;
  overflow: hidden;
  mask-image: linear-gradient(0deg, #000 55%, transparent);
  -webkit-mask-image: linear-gradient(0deg, #000 55%, transparent);
}
.ev-abstract-key {
  display: inline-block;
  min-width: 30px;
  margin-right: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-text);
}

/* ── 连续上下文 ──
 * 关键点：
 *  1. 命中段落用 inline + box-shadow 铺底，box-decoration-break: clone
 *     让换行处底色连续（否则每行一段，看起来像多块）
 *  2. 上下文用 mask 渐隐表示「还有更多」，而不是加省略号再切一刀
 *  3. 只留章节切换点的小圆点标记，不加边框/padding/展开按钮
 */
.ev-passage {
  font-size: 13px;
  line-height: 2.05;
  letter-spacing: 0.1px;
  color: var(--text-2);
}
.ev-passage p {
  margin: 0 0 12px;
}
.ev-passage p:last-child {
  margin-bottom: 0;
}

.ev-passage-mark {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 15px 0 8px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--accent-text);
}
.ev-passage-mark::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--accent);
}
.ev-passage-mark.is-nb {
  color: var(--faint);
}
.ev-passage-mark.is-nb::before {
  background: var(--border-strong);
}
.ev-passage-lbl {
  flex: none;
  font-family: var(--font-sans);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--faint);
}

.ev-passage-nb {
  color: var(--muted);
  opacity: 0.72;
}
.ev-passage-nb.is-top {
  mask-image: linear-gradient(180deg, transparent 0%, #000 42%);
  -webkit-mask-image: linear-gradient(180deg, transparent 0%, #000 42%);
}
.ev-passage-nb.is-bot {
  mask-image: linear-gradient(0deg, transparent 0%, #000 42%);
  -webkit-mask-image: linear-gradient(0deg, transparent 0%, #000 42%);
}

/* 命中段落组 = 一个整块底色。
 *
 * 曾经的做法是给每个 `<span>` 加 `box-shadow: 0 0 0 5px` 铺底 + 段间距 6px。
 * 段间距小于 2×5px，上下两段的阴影**互相接上**，整片变成一块蓝板：
 * 高亮反而把正文糊住了（真实截图确认过）。
 *
 * 现在的分工：
 *   - `.ev-passage-hit-group` 负责**一整块连续的底色**（段之间不漏白）
 *   - `.ev-passage-hit` 只负责**行内换行处不断开**（box-decoration-break）
 * 两者叠加才是「一段连续文本 + 淡淡的高亮区域」。
 */
.ev-passage-hit-group {
  background: color-mix(in srgb, var(--accent) 11%, transparent);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 0 0 12px;
}
.ev-passage-hit-group .ev-passage-hit-line {
  margin: 0 0 8px;
}
.ev-passage-hit-group .ev-passage-hit-line:last-child {
  margin-bottom: 0;
}
.ev-passage-hit {
  /* 不再用 box-shadow 铺满，只保留换行处不断开 */
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

/* 只看命中：隐藏前后文与它们的标记 */
.ev-passage.only-hit .ev-passage-nb,
.ev-passage.only-hit .ev-passage-mark.is-nb {
  display: none;
}

.ev-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  transition:
    background-color 0.15s,
    color 0.15s;
}
.ev-btn:hover {
  background: var(--surface);
  color: var(--text);
}
</style>
