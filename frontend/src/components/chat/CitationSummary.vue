<script setup lang="ts">
import type { Citation } from '@/types'
import { ref } from 'vue'
import { BookOpen, ChevronDown, FileText, ExternalLink } from 'lucide-vue-next'

defineProps<{
  citations: Citation[]
}>()

const emit = defineEmits<{
  'select-citation': [citation: Citation]
}>()

const expanded = ref(false)
</script>

<template>
  <div v-if="citations.length > 0" class="pt-2">
    <!-- Toggle header -->
    <button
      class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-primary-200 hover:text-primary-600 hover:shadow"
      @click="expanded = !expanded"
    >
      <BookOpen :size="12" />
      参考文献 · {{ citations.length }}
      <ChevronDown
        :size="12"
        class="transition-transform duration-150"
        :class="{ 'rotate-180': expanded }"
      />
    </button>

    <!-- Reference list -->
    <div
      v-if="expanded"
      class="mt-2 space-y-2"
    >
      <div
        v-for="cite in citations"
        :key="cite.id"
        class="group cursor-pointer rounded-lg border border-slate-100 bg-white px-3 py-2.5 shadow-sm transition-all hover:border-primary-200 hover:bg-primary-50/30 hover:shadow"
        @click="emit('select-citation', cite)"
      >
        <div class="flex items-start gap-2">
          <span class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-primary-100 text-[10px] font-bold text-primary-600 mt-0.5">
            {{ cite.id }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-semibold text-slate-800 leading-snug line-clamp-1">
              {{ cite.title }}
            </p>
            <div class="mt-0.5 flex items-center gap-2">
              <span class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                <FileText :size="9" />
                {{ cite.source }}
              </span>
              <span v-if="cite.page" class="text-[10px] text-slate-400">
                P.{{ cite.page }}
              </span>
            </div>
            <p class="mt-1 text-[11px] leading-relaxed text-slate-500 line-clamp-2">
              {{ cite.snippet }}
            </p>
          </div>
          <ExternalLink
            :size="12"
            class="mt-1 shrink-0 text-slate-300 opacity-0 transition-all group-hover:opacity-100 group-hover:text-primary-400"
          />
        </div>
      </div>
    </div>
  </div>
</template>
