<script setup lang="ts">
import type { Message } from '@/types'
import UserMessage from './UserMessage.vue'
import AiMessage from './AiMessage.vue'

defineProps<{
  message: Message
  isStreaming?: boolean
  streamContent?: string
}>()
</script>

<template>
  <UserMessage v-if="message.role === 'user'" :message="message" />
  <AiMessage
    v-else
    :message="message"
    :is-streaming="isStreaming"
    :stream-content="streamContent"
  />
</template>
