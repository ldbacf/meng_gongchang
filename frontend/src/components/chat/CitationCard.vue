<script setup lang="ts">
import type { Citation } from '@/types'
import { ref } from 'vue'
import { ExternalLink, BookOpen, X, FileText } from 'lucide-vue-next'

defineProps<{ citation: Citation }>()

const showModal = ref(false)
</script>

<template>
  <!-- Card -->
  <div
    class="group rounded-xl border bg-white p-3 hover:shadow-sm transition-all duration-200 cursor-pointer"
    @click="showModal = true"
  >
    <div class="flex items-start gap-2">
      <BookOpen :size="15" class="mt-0.5 shrink-0 text-primary-500" />
      <div class="min-w-0 flex-1">
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
      <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 opacity-0 group-hover:opacity-100 transition-all">
        <ExternalLink :size="14" />
      </div>
    </div>
  </div>

  <!-- PDF Modal -->
  <Teleport to="body">
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-6"
      @click.self="showModal = false"
    >
      <!-- Backdrop -->
      <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" />

      <!-- Modal content -->
      <div class="relative z-10 flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between border-b px-6 py-4">
          <div class="flex items-center gap-3 min-w-0">
            <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-50">
              <FileText :size="18" class="text-primary-600" />
            </div>
            <div class="min-w-0">
              <h3 class="text-sm font-semibold text-slate-800 truncate">
                {{ citation.title }}
              </h3>
              <p class="text-xs text-slate-500">
                {{ citation.source }}
                <span v-if="citation.page"> · 第 {{ citation.page }} 页</span>
              </p>
            </div>
          </div>
          <button
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
            @click="showModal = false"
          >
            <X :size="18" />
          </button>
        </div>

        <!-- Mock PDF viewer -->
        <div class="flex-1 overflow-y-auto bg-slate-50 p-6">
          <div class="rounded-xl border bg-white shadow-sm overflow-hidden">
            <!-- Mock PDF toolbar -->
            <div class="flex items-center gap-2 border-b bg-slate-100/50 px-4 py-2">
              <span class="text-xs text-slate-500">PDF 预览</span>
              <span class="ml-auto text-[11px] text-slate-400">第 {{ citation.page ?? 1 }} 页</span>
            </div>
            <!-- Mock PDF content -->
            <div class="p-8 space-y-4">
              <div class="flex items-center gap-3 pb-4 border-b border-dashed">
                <BookOpen :size="20" class="text-primary-500 shrink-0" />
                <div>
                  <p class="text-sm font-semibold text-slate-800">{{ citation.title }}</p>
                  <p class="text-xs text-slate-500">{{ citation.source }}</p>
                </div>
              </div>
              <div class="space-y-3 text-sm leading-relaxed text-slate-700">
                <p class="indent-6">
                  {{ citation.snippet }}
                </p>
                <p class="indent-6 text-slate-500">
                  本文献已通过向量化处理，切片存储于 Milvus 向量库中，支持语义检索与精准召回。
                </p>
              </div>
              <!-- Citation highlight block -->
              <div class="rounded-lg border-l-4 border-primary-400 bg-primary-50/50 px-4 py-3">
                <p class="text-xs font-medium text-primary-700 mb-1">关键片段</p>
                <p class="text-sm text-slate-700 leading-relaxed">
                  {{ citation.snippet }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
