<script setup lang="ts">
import type { Message } from '@/types'
import UserMessage from './UserMessage.vue'
import AiMessage from './AiMessage.vue'

defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
}>()

const emit = defineEmits<{ 'citation-click': [id: string] }>()
</script>

<template>
  <UserMessage v-if="message.role === 'user'" :message="message" />
  <AiMessage
    v-else
    :message="message"
    :is-streaming="isStreaming"
    :stream-content="streamContent"
    @citation-click="(id) => emit('citation-click', id)"
  />
</template>
