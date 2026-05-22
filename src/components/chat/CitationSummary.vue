<script setup lang="ts">
import { BookOpen } from 'lucide-vue-next'

defineEmits<{ click: [] }>()
</script>

<template>
  <div class="flex justify-start pt-3 pb-0">
    <button
      class="inline-flex items-center gap-2 rounded-full border border-primary-200 bg-primary-50 px-5 py-1.5 text-xs font-semibold text-primary-700 shadow-sm transition-all duration-200 hover:scale-105 hover:border-primary-300 hover:bg-primary-100 hover:shadow-md"
      @click="$emit('click')"
    >
      <BookOpen :size="14" />
      参考文献
    </button>
  </div>
</template>
