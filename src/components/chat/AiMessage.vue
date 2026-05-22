<script setup lang="ts">
import type { Message, Citation } from '@/types'
import { useMarkdown } from '@/composables/useMarkdown'
import { computed } from 'vue'
import CitationCard from './CitationCard.vue'
import RagPipelineSimple from './RagPipelineSimple.vue'
import { Sparkles } from 'lucide-vue-next'

const props = defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
  streamCitations?: Citation[]
}>()

const emit = defineEmits<{ 'citation-click': [id: string] }>()

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
  if (target?.dataset.citationId) {
    emit('citation-click', target.dataset.citationId)
  }
}

const hasRagSteps = computed(() => {
  const steps = props.message.ragSteps
  return steps && Object.values(steps).some((s) => s !== undefined)
})

const displayCitations = computed(() => {
  if (props.isStreaming && props.streamCitations) {
    return props.streamCitations
  }
  return props.message.citations ?? []
})
</script>

<template>
  <div class="px-4 py-4">
    <div class="flex max-w-[85%] gap-3">
      <!-- Avatar -->
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-sky-400 shadow-sm"
      >
        <Sparkles :size="16" class="text-white" />
      </div>

      <!-- Content -->
      <div class="min-w-0 flex-1">
        <!-- RAG Pipeline -->
        <RagPipelineSimple
          v-if="message.ragSteps && hasRagSteps"
          :steps="message.ragSteps"
        />

        <!-- Markdown body -->
        <div
          v-if="renderedContent"
          class="markdown-body text-sm leading-relaxed text-slate-700"
          v-html="renderedContent"
          @click="handleContentClick"
        />

        <!-- Streaming indicator -->
        <div
          v-if="isStreaming && !streamContent"
          class="flex items-center gap-1 py-1"
        >
          <span
            class="h-2 w-2 animate-bounce rounded-full bg-primary-400"
            style="animation-delay: 0ms"
          />
          <span
            class="h-2 w-2 animate-bounce rounded-full bg-primary-400"
            style="animation-delay: 150ms"
          />
          <span
            class="h-2 w-2 animate-bounce rounded-full bg-primary-400"
            style="animation-delay: 300ms"
          />
        </div>

        <!-- Citations -->
        <div
          v-if="displayCitations.length > 0"
          class="mt-4 space-y-2"
        >
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            参考来源 ({{ displayCitations.length }})
          </p>
          <div class="grid gap-2 sm:grid-cols-2">
            <CitationCard
              v-for="cite in displayCitations"
              :key="cite.id"
              :citation="cite"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
