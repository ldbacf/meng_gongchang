<script setup lang="ts">
import { computed } from 'vue'
import { Pill, LineChart, FlaskConical, BookOpen } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{ ask: [question: string] }>()
const authStore = useAuthStore()

const name = computed(() => authStore.user?.username || '你好')

const suggests = [
  { q: '高血压初始治疗怎么选药？', d: '一线药物、联合时机与合并症考量', icon: Pill },
  { q: '二甲双胍控制不佳后的二线方案怎么选？', d: 'DPP-4i / SGLT2i / GLP-1RA 如何取舍', icon: LineChart },
  { q: 'H 型高血压的叶酸干预证据有哪些？', d: '同型半胱氨酸目标值与疗程', icon: FlaskConical },
  { q: '社区高血压随访管理有哪些规范要求？', d: '随访频次、转诊指征与考核指标', icon: BookOpen },
]
</script>

<template>
  <div class="flex h-full flex-col justify-center px-6 pb-16">
    <div class="mx-auto w-full max-w-chat">
      <h1 class="mb-1.5 text-[38px] font-semibold leading-[1.25] tracking-[-.5px]">
        <span
          class="bg-[linear-gradient(100deg,var(--grad-1),var(--grad-2),var(--grad-3))] bg-clip-text text-transparent"
        >你好，{{ name }}</span>
        <br />
        今天想了解什么？
      </h1>
      <p class="mb-8 text-[15px] text-muted">
        基于 1,248 篇中文医学文献，给出带原文出处的回答。
      </p>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <button
          v-for="s in suggests"
          :key="s.q"
          class="rounded-2xl border border-line bg-surface-2 px-4 pb-4 pt-4 text-left transition-all hover:border-line-strong hover:bg-surface hover:shadow-sm"
          @click="emit('ask', s.q)"
        >
          <component :is="s.icon" :size="18" class="mb-2.5 text-accent" />
          <div class="mb-1 text-[13.5px] font-semibold">{{ s.q }}</div>
          <div class="text-[12.5px] leading-[1.55] text-muted">{{ s.d }}</div>
        </button>
      </div>
    </div>
  </div>
</template>
