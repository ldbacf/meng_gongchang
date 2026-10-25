<script setup lang="ts">
import type { Citation, Message } from '@/types'
import UserMessage from './UserMessage.vue'
import AiMessage from './AiMessage.vue'

defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
  canRegenerate?: boolean
}>()

const emit = defineEmits<{
  'citation-click': [citation: Citation]
  'show-citation-list': []
  regenerate: []
}>()
</script>

<template>
  <UserMessage v-if="message.role === 'user'" :message="message" />
  <AiMessage
    v-else
    :message="message"
    :is-streaming="isStreaming"
    :stream-content="streamContent"
    :can-regenerate="canRegenerate"
    @citation-click="(cite) => emit('citation-click', cite)"
    @show-citation-list="emit('show-citation-list')"
    @regenerate="emit('regenerate')"
  />
</template>
