<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { useToastStore } from '@/stores/toast'
import { useDocumentWS } from '@/composables/useDocumentWS'
import type { DocumentInfo } from '@/types/knowledge'
import AppLayout from '@/components/layout/AppLayout.vue'
import {
  ArrowLeft, Upload, Trash2, FileText, AlertCircle, CheckCircle2,
  Loader2, ShieldCheck, BookOpen, RefreshCw,
} from 'lucide-vue-next'

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

// ── 步骤点 ──

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
  if (st === 'done') return ['bg-ok']
  if (st === 'running') return ['bg-accent', 'animate-pulse', 'running']
  if (st === 'failed') return ['bg-danger']
  return ['bg-line-strong']
}

function connectorClass(doc: DocumentInfo, dotKey: string): string {
  return dotStatus(doc, dotKey)?.status === 'done' ? 'bg-ok' : 'bg-line-strong'
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
  pending:    { label: '等待上传',   color: 'text-faint',  icon: Loader2 },
  processing: { label: 'MinerU 解析中', color: 'text-accent', icon: Loader2 },
  parsed:     { label: '待建立索引', color: 'text-warn',   icon: FileText },
  indexing:   { label: '索引中',     color: 'text-accent', icon: Loader2 },
  ready:      { label: '就绪',       color: 'text-ok',     icon: CheckCircle2 },
  failed:     { label: '失败',       color: 'text-danger', icon: AlertCircle },
}

const stepLabels: Record<string, string> = {
  upload: '上传至 MinIO',
  mineru: 'MinerU 解析',
  chunking: '文档切分',
  embedding: '向量 Embedding',
  es_write: 'ES 写入',
  milvus: 'Milvus 写入',
}

const readyCount = computed(() => adminStore.documents.filter((d) => d.status === 'ready').length)
</script>

<template>
  <AppLayout>
    <div class="flex h-full flex-col overflow-hidden">
      <!-- 页头 -->
      <div class="border-b border-line px-8 pb-5 pt-2">
        <div class="flex items-start justify-between gap-4">
          <div class="flex min-w-0 items-start gap-2">
            <button
              class="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
              @click="goBack"
            >
              <ArrowLeft :size="16" />
            </button>
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <h1 class="truncate text-[22px] font-semibold tracking-[-.3px]">{{ kb?.name || '加载中…' }}</h1>
                <span
                  class="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                  :class="isReadOnly ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'"
                >
                  <ShieldCheck v-if="isReadOnly" :size="11" />
                  <BookOpen v-else :size="11" />
                  {{ isReadOnly ? '只读' : '可上传' }}
                </span>
              </div>
              <p class="mt-1 truncate text-[13px] text-muted">{{ kb?.description || '' }}</p>
            </div>
          </div>

          <div class="flex shrink-0 items-center gap-1.5">
            <span
              class="mr-1 h-[7px] w-[7px] shrink-0 rounded-full"
              :class="wsConnected ? 'bg-ok' : 'bg-danger'"
              :title="wsConnected ? '实时连接已建立' : '实时连接断开'"
            />
            <span class="mr-1 text-[11.5px] text-faint">
              {{ adminStore.documents.length }} 篇 · 就绪 {{ readyCount }}
            </span>

            <button
              :disabled="refreshing"
              class="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink disabled:opacity-50"
              title="刷新"
              @click="refreshDocs"
            >
              <RefreshCw :size="15" :class="{ 'animate-spin': refreshing }" />
            </button>

            <button
              v-if="!isReadOnly"
              :disabled="uploading"
              class="flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
              @click="triggerUpload"
            >
              <Upload :size="15" />
              {{ uploading ? '上传中…' : '上传文档' }}
            </button>
          </div>
        </div>
        <input ref="fileInput" type="file" accept=".pdf,.txt,.doc,.docx,.md" class="hidden" @change="handleFileChange" />
      </div>

      <!-- 文档列表 -->
      <div class="flex-1 overflow-y-auto px-8 py-5">
        <div
          v-if="adminStore.documents.length === 0"
          class="flex flex-col items-center justify-center py-24 text-faint"
        >
          <FileText :size="34" class="mb-3 opacity-60" />
          <p class="text-[13px]">暂无上传文档</p>
          <p v-if="!isReadOnly" class="mt-1 text-[12px]">点击「上传文档」添加医学文献</p>
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="doc in adminStore.documents"
            :key="doc.id"
            class="doc-row flex items-center gap-3.5 rounded-xl border border-line bg-surface-2 px-4 py-3 transition-shadow hover:shadow-sm"
          >
            <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface">
              <FileText :size="17" class="text-muted" />
            </div>

            <div class="min-w-0 flex-1" @click="toggleExpand(doc.id)" style="cursor:pointer">
              <p class="truncate text-[13.5px] font-medium">{{ doc.original_name }}</p>

              <div class="mt-1.5 flex items-center gap-2">
                <span class="font-mono text-[10.5px] text-faint">{{ doc.md5.slice(0, 6) }}</span>

                <template v-if="stepOrderDots.length > 0">
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
                  class="flex shrink-0 items-center gap-1 text-[11px]"
                  :class="statusConfig[doc.status]?.color || 'text-faint'"
                >
                  <component
                    :is="statusConfig[doc.status]?.icon || Loader2"
                    :size="11"
                    :class="{ 'animate-spin': !['ready', 'failed'].includes(doc.status) }"
                  />
                  {{ statusConfig[doc.status]?.label || doc.status }}
                </span>

                <span v-if="doc.error_msg" class="max-w-[180px] truncate text-[10.5px] text-danger">
                  {{ doc.error_msg }}
                </span>

                <button
                  v-if="doc.status === 'failed'"
                  class="shrink-0 rounded-full border border-line px-2 py-0.5 text-[10.5px] font-medium text-danger transition-colors hover:bg-danger-soft"
                  @click.stop="handleRetry(doc.id)"
                >重试</button>
              </div>

              <!-- 展开的步骤明细 -->
              <div v-if="expandedDocs.has(doc.id) && doc.pipeline_steps" class="mt-2.5 border-t border-line pt-2">
                <div v-for="key in stepOrderDetail" :key="key" class="flex items-center gap-2 py-1 text-[11.5px]">
                  <template v-if="doc.pipeline_steps[key]">
                    <CheckCircle2 v-if="doc.pipeline_steps[key].status === 'done'" :size="11" class="shrink-0 text-ok" />
                    <Loader2 v-else-if="doc.pipeline_steps[key].status === 'running'" :size="11" class="shrink-0 animate-spin text-accent" />
                    <AlertCircle v-else-if="doc.pipeline_steps[key].status === 'failed'" :size="11" class="shrink-0 text-danger" />
                    <span v-else class="h-2.5 w-2.5 shrink-0 rounded-full border border-line-strong" />

                    <span class="w-[104px] shrink-0 text-muted">{{ stepLabels[key] || key }}</span>
                    <span
                      v-if="doc.pipeline_steps[key].status === 'failed' && doc.pipeline_steps[key].error"
                      class="truncate text-danger"
                    >{{ doc.pipeline_steps[key].error }}</span>
                    <span v-if="doc.pipeline_steps[key].target_index" class="ml-auto text-faint">{{ doc.pipeline_steps[key].target_index }}</span>
                    <span v-if="doc.pipeline_steps[key].target_collection" class="text-faint">{{ doc.pipeline_steps[key].target_collection }}</span>
                    <span v-if="doc.pipeline_steps[key].count" class="ml-auto text-faint">×{{ doc.pipeline_steps[key].count }}</span>
                  </template>
                </div>
              </div>
            </div>

            <button
              class="grid h-8 w-8 shrink-0 place-items-center rounded-full text-faint transition-colors hover:bg-danger-soft hover:text-danger"
              title="删除"
              @click="handleDelete(doc.id)"
            >
              <Trash2 :size="15" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
/* 运行中的步骤点：脉冲光环 */
@keyframes step-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(26, 115, 232, 0.35); }
  50%      { box-shadow: 0 0 0 4px rgba(26, 115, 232, 0); }
}

.step-dot { transition: background-color 0.3s ease; }
.step-dot.running { animation: step-pulse 1.5s ease-in-out infinite; }

.doc-row { transition: box-shadow 0.2s ease; }
</style>
