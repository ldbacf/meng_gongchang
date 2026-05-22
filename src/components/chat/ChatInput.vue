<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { Send } from 'lucide-vue-next'

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const emit = defineEmits<{ send: [content: string] }>()

defineProps<{ disabled?: boolean }>()

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.rows = 1
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20
  const maxRows = 6
  const maxHeight = lineHeight * maxRows
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, maxHeight) + 'px'
  el.rows = Math.min(maxRows, Math.max(1, Math.floor(el.scrollHeight / lineHeight)))
}

async function handleSend() {
  const content = text.value.trim()
  if (!content) return
  emit('send', content)
  text.value = ''
  await nextTick()
  autoResize()
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="border-t bg-white/60 px-4 py-4 backdrop-blur-xl">
    <div class="flex justify-center">
      <div class="w-full max-w-3xl">
      <div
        class="flex items-center gap-3 rounded-2xl border border-slate-200/60 bg-white/70 px-4 py-3 shadow-sm backdrop-blur-sm transition-all duration-200 focus-within:border-primary-300 focus-within:bg-white/90 focus-within:shadow-md focus-within:ring-2 focus-within:ring-primary-100"
      >
        <textarea
          ref="textareaRef"
          v-model="text"
          :disabled="disabled"
          rows="1"
          placeholder="输入您的医学问题..."
          class="max-h-36 min-h-[24px] flex-1 resize-none border-0 bg-transparent p-0 text-sm text-slate-900 placeholder-slate-400 outline-none disabled:opacity-50"
          @keydown="handleKeydown"
          @input="autoResize"
        />
        <button
          :disabled="disabled || !text.trim()"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm transition-all hover:bg-primary-700 disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none"
          @click="handleSend"
        >
          <Send :size="16" />
        </button>
      </div>
      <p class="mt-2 text-center text-xs text-slate-400">
        MedRAG 可能产生不准确信息，请核对引文来源。Enter 发送，Shift+Enter 换行。
      </p>
    </div>
    </div>
  </div>
</template>
