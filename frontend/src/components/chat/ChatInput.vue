<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ArrowUp, Square, Paperclip } from 'lucide-vue-next'

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const emit = defineEmits<{ send: [content: string]; stop: [] }>()

const props = defineProps<{ disabled?: boolean; streaming?: boolean }>()

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}

async function handleSend() {
  if (props.streaming) return
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
  <div class="px-6 pb-4 pt-1">
    <div class="mx-auto w-full max-w-chat">
      <!-- 聚焦不用 outline：加一圈 1px 强调色 + 3px 柔和外环，形成"咬合"的双环 -->
      <div
        class="rounded-[28px] border border-line bg-surface-2 transition-[border-color,box-shadow] duration-200 ease-[cubic-bezier(.215,.61,.355,1)] focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft),0_0_0_1px_var(--accent)]"
      >
        <div class="flex items-end gap-2 py-2 pl-3.5 pr-2">
          <button
            class="mb-1 grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
            title="添加附件"
          >
            <Paperclip :size="17" />
          </button>

          <textarea
            ref="textareaRef"
            v-model="text"
            rows="1"
            :disabled="disabled || streaming"
            placeholder="向 MedRAG 提问，例如：高血压初始治疗怎么选药？"
            class="max-h-[180px] min-h-[24px] flex-1 resize-none border-0 bg-transparent py-2.5 text-[15px] leading-normal text-ink placeholder:text-faint outline-none disabled:opacity-60"
            @keydown="handleKeydown"
            @input="autoResize"
          />

          <button
            v-if="streaming"
            class="mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-canvas transition-transform active:scale-95"
            title="停止生成"
            @click="emit('stop')"
          >
            <Square :size="14" fill="currentColor" />
          </button>
          <button
            v-else
            :disabled="disabled || !text.trim()"
            class="mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent text-white shadow-[0_2px_8px_rgba(26,115,232,.35)] transition-[background-color,transform] duration-200 ease-[cubic-bezier(.34,1.56,.64,1)] hover:bg-accent-hover active:scale-90 disabled:bg-surface disabled:text-faint disabled:shadow-none"
            title="发送"
            @click="handleSend"
          >
            <ArrowUp :size="17" />
          </button>
        </div>

        <div class="flex items-center gap-2 px-4 pb-2.5 text-[11px] text-faint">
          <kbd class="rounded border border-line bg-surface px-1.5 py-px font-mono text-[10.5px]">Enter</kbd>
          发送
          <kbd class="rounded border border-line bg-surface px-1.5 py-px font-mono text-[10.5px]">Shift + Enter</kbd>
          换行
        </div>
      </div>

      <p class="mt-2.5 text-center text-[11px] text-faint">
        回答基于文献原文，仅供临床参考；模型可能出错，请核对出处。
      </p>
    </div>
  </div>
</template>
