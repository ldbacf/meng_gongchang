<script setup lang="ts">
import type { Citation } from '@/types'
import { ExternalLink, BookOpen } from 'lucide-vue-next'

defineProps<{ citation: Citation }>()
</script>

<template>
  <div
    class="group rounded-xl border bg-white p-3 hover:shadow-sm transition-all duration-200 cursor-default"
  >
    <div class="flex items-start gap-2">
      <BookOpen :size="15" class="mt-0.5 shrink-0 text-primary-500" />
      <div class="min-w-0">
        <p class="text-sm font-medium text-slate-800 truncate">
          {{ citation.title }}
        </p>
        <p class="text-xs text-slate-500 mt-0.5">
          {{ citation.source }}
          <span v-if="citation.page"> · p.{{ citation.page }}</span>
        </p>
        <p class="mt-1.5 text-xs leading-relaxed text-slate-600 line-clamp-2">
          {{ citation.snippet }}
        </p>
      </div>
      <a
        v-if="citation.url"
        :href="citation.url"
        target="_blank"
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-slate-100 hover:text-primary-600 transition-all"
        @click.stop
      >
        <ExternalLink :size="14" />
      </a>
    </div>
  </div>
</template>
