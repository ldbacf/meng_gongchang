<script setup lang="ts">
import type { Citation, Message } from '@/types'
import UserMessage from './UserMessage.vue'
import AiMessage from './AiMessage.vue'

defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
}>()

const emit = defineEmits<{
  'citation-click': [citation: Citation]
  'show-citation-list': []
}>()
</script>

<template>
  <UserMessage v-if="message.role === 'user'" :message="message" />
  <AiMessage
    v-else
    :message="message"
    :is-streaming="isStreaming"
    :stream-content="streamContent"
    @citation-click="(cite) => emit('citation-click', cite)"
    @show-citation-list="emit('show-citation-list')"
  />
</template>
