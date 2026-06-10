<script setup lang="ts">
import type { Message } from '@/types'
import { ref } from 'vue'
import { User, Copy, Check } from 'lucide-vue-next'

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
  <div class="group flex justify-end px-4 py-3">
    <div class="flex max-w-[75%] items-end gap-2.5">
      <div class="relative">
        <div
          class="rounded-2xl rounded-br-md bg-primary-600/85 px-4 py-2.5 text-sm leading-relaxed text-white shadow-md backdrop-blur-sm"
        >
          {{ message.content }}
        </div>
        <button
          class="absolute bottom-1 right-1 flex h-5 w-5 items-center justify-center rounded text-white/40 transition-all hover:bg-white/20 hover:text-white active:scale-90"
          title="复制"
          @click="copyContent"
        >
          <Check v-if="copied" :size="11" class="text-emerald-300" />
          <Copy v-else :size="11" />
        </button>
      </div>
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200"
      >
        <User :size="16" class="text-slate-500" />
      </div>
    </div>
  </div>
</template>
