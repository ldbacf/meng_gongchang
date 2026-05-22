<script setup lang="ts">
import type { Message } from '@/types'
import { User } from 'lucide-vue-next'

defineProps<{ message: Message }>()
</script>

<template>
  <div class="flex justify-end px-4 py-3">
    <div class="flex max-w-[75%] items-end gap-2.5">
      <div
        class="rounded-2xl rounded-br-md bg-primary-600/85 px-4 py-2.5 text-sm leading-relaxed text-white shadow-md backdrop-blur-sm"
      >
        {{ message.content }}
      </div>
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200"
      >
        <User :size="16" class="text-slate-500" />
      </div>
    </div>
  </div>
</template>
