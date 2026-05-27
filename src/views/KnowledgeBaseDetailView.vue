<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { useToastStore } from '@/stores/toast'
import { useDocumentWS } from '@/composables/useDocumentWS'
import type { DocumentInfo } from '@/types/knowledge'
import AppLayout from '@/components/layout/AppLayout.vue'
import { ArrowLeft, Upload, Trash2, FileText, AlertCircle, CheckCircle2, Loader2, ShieldCheck, BookOpen, RefreshCw } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()
const toastStore = useToastStore()

const kbId = computed(() => route.params.kbId as string)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const expandedDocs = ref<Set<string>>(new Set())

function toggleExpand(docId: string) {
  if (expandedDocs.value.has(docId)) {
    expandedDocs.value.delete(docId)
  } else {
    expandedDocs.value.add(docId)
  }
  expandedDocs.value = new Set(expandedDocs.value)
}

const kb = computed(() => adminStore.knowledgeBases.find((k) => k.id === kbId.value))
const isReadOnly = computed(() => kb.value?.slug === 'zhong_guo_quan_ke')

onMounted(async () => {
  if (adminStore.knowledgeBases.length === 0) {
    await adminStore.fetchKnowledgeBases()
  }
  await adminStore.fetchDocuments(kbId.value)
})

// ── WebSocket ──

const { connected: wsConnected } = useDocumentWS(kbId)

// ── Refresh ──

const refreshing = ref(false)
async function refreshDocs() {
  refreshing.value = true
  try {
    await adminStore.fetchDocuments(kbId.value)
  } finally {
    refreshing.value = false
  }
}

// ── Inline step dots ──

const stepOrderDetail = ['upload', 'mineru', 'chunking', 'embedding', 'es_write', 'milvus']

const stepOrderDots = computed(() => {
  if (isReadOnly.value) return []
  return ['upload', 'mineru', 'indexing']
})

const dotNames: Record<string, string> = {
  upload: '上传',
  mineru: '解析',
  indexing: '索引',
}

/** 获取单个点的状态。indexing 点由 4 个索引子步骤综合推导 */
function dotStatus(doc: DocumentInfo, dotKey: string): { status: string } | null {
  if (dotKey === 'indexing') {
    const subs = ['chunking', 'embedding', 'es_write', 'milvus']
    const steps = doc.pipeline_steps
    if (!steps) return null
    const s = subs.map(k => steps[k]).filter(Boolean)
    if (s.length === 0) return null
    if (s.some(x => x.status === 'failed')) return { status: 'failed' }
    if (s.some(x => x.status === 'running')) return { status: 'running' }
    if (s.every(x => x.status === 'done')) return { status: 'done' }
    return null
  }
  return doc.pipeline_steps?.[dotKey] || null
}

function dotClass(doc: DocumentInfo, dotKey: string): string[] {
  const st = dotStatus(doc, dotKey)?.status || null
  if (st === 'done') return ['bg-emerald-400']
  if (st === 'running') return ['bg-blue-400', 'animate-pulse', 'running']
  if (st === 'failed') return ['bg-red-400']
  return ['bg-slate-200']
}

function connectorClass(doc: DocumentInfo, dotKey: string): string {
  return dotStatus(doc, dotKey)?.status === 'done' ? 'bg-emerald-200' : 'bg-slate-200'
}

function goBack() {
  router.push('/admin/knowledge')
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    await adminStore.uploadDocument(kbId.value, file)
    toastStore.success('文件已提交，后台处理中')
  } catch (err: any) {
    toastStore.error(err?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function handleDelete(docId: string) {
  try {
    await adminStore.deleteDocument(docId)
    toastStore.success('文档已删除')
  } catch {
    toastStore.error('删除失败')
  }
}

async function handleRetry(docId: string) {
  try {
    const res = await adminStore.retryDocument(docId)
    toastStore.success(`从「${res.retry_from}」步骤重试`)
  } catch (e: any) {
    toastStore.error(e?.response?.data?.detail || '重试失败')
  }
}

const statusConfig: Record<string, { label: string; color: string; icon: unknown }> = {
  pending: { label: '等待上传', color: 'text-slate-400', icon: Loader2 },
  processing: { label: 'MinerU 解析中', color: 'text-blue-500', icon: Loader2 },
  parsed: { label: '待建立索引', color: 'text-amber-500', icon: FileText },
  indexing: { label: '索引中', color: 'text-purple-500', icon: Loader2 },
  ready: { label: '就绪', color: 'text-emerald-500', icon: CheckCircle2 },
  failed: { label: '失败', color: 'text-red-500', icon: AlertCircle },
}

const stepLabels: Record<string, string> = {
  upload: '上传至 MinIO',
  mineru: 'MinerU 解析',
  chunking: '文档切分',
  embedding: '向量 Embedding',
  es_write: 'ES 写入',
  milvus: 'Milvus 写入',
}
</script>

<template>
  <AppLayout>
    <div class="flex h-full flex-col">
      <!-- Header -->
      <div class="flex items-center justify-between border-b px-6 py-4">
        <div class="flex items-center gap-3">
          <button class="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-slate-100 transition-colors" @click="goBack">
            <ArrowLeft :size="18" class="text-slate-500" />
          </button>
          <div>
            <div class="flex items-center gap-2">
              <h1 class="text-lg font-semibold text-slate-800">{{ kb?.name || '加载中...' }}</h1>
              <span
                class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                :class="isReadOnly ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'"
              >
                <ShieldCheck v-if="isReadOnly" :size="12" />
                <BookOpen v-else :size="12" />
                {{ isReadOnly ? '只读' : '可上传' }}
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5">{{ kb?.description || '' }}</p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <!-- WS status dot -->
          <span
            class="flex h-2 w-2 rounded-full shrink-0"
            :class="wsConnected ? 'bg-emerald-400' : 'bg-red-400'"
            :title="wsConnected ? '实时连接已建立' : '实时连接断开'"
          />

          <button
            :disabled="refreshing"
            class="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-slate-100 transition-colors disabled:opacity-50"
            title="刷新文档列表"
            @click="refreshDocs"
          >
            <RefreshCw :size="16" class="text-slate-500" :class="{ 'animate-spin': refreshing }" />
          </button>

          <button
            v-if="!isReadOnly"
            :disabled="uploading"
            class="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 active:scale-[0.98] transition-colors shadow-sm disabled:opacity-50"
            @click="triggerUpload"
          >
            <Upload :size="16" />
            {{ uploading ? '上传中...' : '上传文档' }}
          </button>
        </div>
        <input ref="fileInput" type="file" accept=".pdf,.txt,.doc,.docx,.md" class="hidden" @change="handleFileChange" />
      </div>

      <!-- Document List -->
      <div class="flex-1 overflow-y-auto p-6">
        <div v-if="adminStore.documents.length === 0" class="flex flex-col items-center justify-center py-20 text-slate-400">
          <FileText :size="48" class="mb-4" />
          <p class="text-sm">暂无上传文档</p>
          <p v-if="!isReadOnly" class="text-xs mt-1">点击"上传文档"添加医学文献</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="doc in adminStore.documents"
            :key="doc.id"
            class="doc-row flex items-center gap-4 rounded-xl border bg-white p-4 hover:shadow-sm"
          >
            <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100">
              <FileText :size="20" class="text-slate-500" />
            </div>

            <div class="flex-1 min-w-0" @click="toggleExpand(doc.id)" style="cursor:pointer">
              <p class="text-sm font-medium text-slate-800 truncate">{{ doc.original_name }}</p>
              <!-- Step dots bar -->
              <div class="mt-1.5 flex items-center gap-1.5">
                <template v-if="stepOrderDots.length > 0">
                  <span class="text-[10px] text-slate-400 font-mono mr-1">{{ doc.md5.slice(0, 6) }}</span>
                  <div v-for="(dotKey, si) in stepOrderDots" :key="dotKey" class="flex items-center gap-0.5">
                    <div
                      class="step-dot h-1.5 w-1.5 rounded-full"
                      :class="dotClass(doc, dotKey)"
                      :title="`${dotNames[dotKey]}: ${dotStatus(doc, dotKey)?.status || 'pending'}`"
                    />
                    <div v-if="si < stepOrderDots.length - 1" class="h-px w-2" :class="connectorClass(doc, dotKey)" />
                  </div>
                </template>
                <span
                  class="flex items-center gap-0.5 text-[10px] shrink-0 ml-1"
                  :class="statusConfig[doc.status]?.color || 'text-slate-400'"
                >
                  <component
                    :is="statusConfig[doc.status]?.icon || Loader2"
                    :size="11"
                    :class="{ 'animate-spin': !['ready', 'failed'].includes(doc.status) }"
                  />
                  {{ statusConfig[doc.status]?.label || doc.status }}
                </span>
                <span v-if="doc.error_msg" class="text-[10px] text-red-400 truncate max-w-[120px]">{{ doc.error_msg }}</span>
                <button
                  v-if="doc.status === 'failed'"
                  class="ml-1 inline-flex items-center gap-0.5 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-600 hover:bg-red-100 transition-colors shrink-0"
                  @click.stop="handleRetry(doc.id)"
                >重试</button>
              </div>
              <!-- Expanded detail -->
              <div v-if="expandedDocs.has(doc.id) && doc.pipeline_steps" class="mt-2 border-t pt-2">
                <div v-for="key in stepOrderDetail" :key="key" class="flex items-center gap-2 py-0.5 text-[11px]">
                  <template v-if="doc.pipeline_steps[key]">
                    <CheckCircle2 v-if="doc.pipeline_steps[key].status === 'done'" :size="12" class="text-emerald-400 shrink-0" />
                    <Loader2 v-else-if="doc.pipeline_steps[key].status === 'running'" :size="12" class="text-blue-400 animate-spin shrink-0" />
                    <AlertCircle v-else-if="doc.pipeline_steps[key].status === 'failed'" :size="12" class="text-red-400 shrink-0" />
                    <span v-else class="h-3 w-3 shrink-0 rounded-full border border-slate-200" />
                    <span class="text-slate-500 w-20 shrink-0">{{ stepLabels[key] || key }}</span>
                    <span v-if="doc.pipeline_steps[key].status === 'failed' && doc.pipeline_steps[key].error" class="text-red-400 truncate">{{ doc.pipeline_steps[key].error }}</span>
                    <span v-if="doc.pipeline_steps[key].target_index" class="text-slate-300 ml-auto">{{ doc.pipeline_steps[key].target_index }}</span>
                    <span v-if="doc.pipeline_steps[key].target_collection" class="text-slate-300">{{ doc.pipeline_steps[key].target_collection }}</span>
                    <span v-if="doc.pipeline_steps[key].count" class="text-slate-300 ml-auto">×{{ doc.pipeline_steps[key].count }}</span>
                  </template>
                </div>
              </div>
            </div>

            <button
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500 transition-colors"
              @click="handleDelete(doc.id)"
            >
              <Trash2 :size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
/* Running step: pulse + glow ring */
@keyframes step-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(59, 130, 246, 0); }
}

.step-dot {
  transition: background-color 0.3s ease;
}

.step-dot.running {
  animation: step-pulse 1.5s ease-in-out infinite;
}

/* Done step: brief scale pop */
@keyframes step-pop {
  0% { transform: scale(1); }
  50% { transform: scale(1.8); }
  100% { transform: scale(1); }
}

.step-dot.just-done {
  animation: step-pop 0.4s ease-out;
}

/* Document row: status transition fade */
.doc-row {
  transition: box-shadow 0.2s ease;
}
</style>
