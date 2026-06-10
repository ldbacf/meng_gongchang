<script setup lang="ts">
import { Stethoscope } from 'lucide-vue-next'

defineProps<{ collapsed?: boolean }>()
</script>

<template>
  <div class="flex items-center gap-3 px-3 py-4">
    <div
      class="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm"
    >
      <Stethoscope :size="20" />
    </div>
    <transition name="fade">
      <span
        v-if="!collapsed"
        class="text-lg font-semibold tracking-tight text-slate-800 whitespace-nowrap"
      >
        MedRAG
      </span>
    </transition>
  </div>
</template>
