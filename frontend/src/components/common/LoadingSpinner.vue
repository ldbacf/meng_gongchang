<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'

defineProps<{ size?: number; text?: string }>()
</script>

<template>
  <div class="flex items-center justify-center gap-2 py-8 text-slate-500">
    <Loader2 :size="size ?? 20" class="animate-spin" />
    <span v-if="text" class="text-sm">{{ text }}</span>
  </div>
</template>
