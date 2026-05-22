<script setup lang="ts">
import { BookOpen } from 'lucide-vue-next'

defineProps<{ count: number }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <div class="flex justify-center py-4">
    <button
      class="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-5 py-2.5 text-sm font-medium text-blue-700 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-100 hover:shadow-md"
      @click="$emit('click')"
    >
      <BookOpen :size="16" />
      参考文献 ({{ count }})
    </button>
  </div>
</template>
