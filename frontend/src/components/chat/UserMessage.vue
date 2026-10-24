<script setup lang="ts">
import type { Message } from '@/types'
import { ref } from 'vue'
import { Copy, Check } from 'lucide-vue-next'

const props = defineProps<{ message: Message }>()
const copied = ref(false)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* fallback */ }
}
</script>

<template>
  <div class="group flex justify-end py-4">
    <div class="relative max-w-[85%]">
      <div
        class="whitespace-pre-wrap break-words rounded-[18px] rounded-br-[4px] bg-surface px-4 py-2.5 text-[14.5px] leading-[1.65] text-ink"
      >
        {{ message.content }}
      </div>
      <button
        class="absolute -left-8 top-1.5 grid h-6 w-6 place-items-center rounded-full text-faint opacity-0 transition-all hover:bg-surface hover:text-ink group-hover:opacity-100"
        title="复制"
        @click="copyContent"
      >
        <Check v-if="copied" :size="12" class="text-ok" />
        <Copy v-else :size="12" />
      </button>
    </div>
  </div>
</template>
