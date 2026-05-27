<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { useToastStore } from '@/stores/toast'
import AppLayout from '@/components/layout/AppLayout.vue'
import { Plus, BookOpen, Trash2, ShieldCheck, ArrowRight } from 'lucide-vue-next'

const adminStore = useAdminStore()
const toastStore = useToastStore()
const router = useRouter()

function activateKb(kb: { id: string; name: string }) {
  adminStore.setActiveKb(kb.id)
  toastStore.success(`已切换到「${kb.name}」，对话将检索该知识库`)
}

const showCreateModal = ref(false)
const newName = ref('')
const newSlug = ref('')
const newDesc = ref('')
const creating = ref(false)

onMounted(() => {
  adminStore.fetchKnowledgeBases()
})

function openCreate() {
  newName.value = ''
  newSlug.value = ''
  newDesc.value = ''
  showCreateModal.value = true
}

async function handleCreate() {
  if (!newName.value.trim() || !newSlug.value.trim()) return
  creating.value = true
  try {
    await adminStore.createKnowledgeBase({
      name: newName.value.trim(),
      slug: newSlug.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'),
      description: newDesc.value.trim() || null,
    })
    showCreateModal.value = false
    toastStore.success('知识库创建成功')
  } catch (e: any) {
    toastStore.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function handleDelete(kbId: string) {
  try {
    await adminStore.deleteKnowledgeBase(kbId)
    toastStore.success('知识库已删除')
  } catch (e: any) {
    toastStore.error(e?.response?.data?.detail || '删除失败')
  }
}

function goToKB(kbId: string) {
  router.push(`/admin/knowledge/${kbId}`)
}
</script>

<template>
  <AppLayout>
    <div class="flex h-full flex-col">
      <!-- Header -->
      <div class="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 class="text-lg font-semibold text-slate-800">知识库管理</h1>
          <p class="text-sm text-slate-500">管理多个医学文献知识库，每个知识库独立存储与检索</p>
        </div>
        <button
          class="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 active:scale-[0.98] transition-colors shadow-sm"
          @click="openCreate"
        >
          <Plus :size="16" />
          新建知识库
        </button>
      </div>

      <!-- KB Card Grid -->
      <div class="flex-1 overflow-y-auto p-6">
        <div v-if="adminStore.kbLoading" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="i in 3" :key="i" class="animate-pulse rounded-xl border bg-white p-5">
            <div class="h-5 w-32 rounded bg-slate-200 mb-3" />
            <div class="h-3 w-full rounded bg-slate-100 mb-2" />
            <div class="h-3 w-3/4 rounded bg-slate-100" />
          </div>
        </div>

        <div v-else-if="adminStore.knowledgeBases.length === 0" class="flex flex-col items-center justify-center py-20 text-slate-400">
          <BookOpen :size="48" class="mb-4" />
          <p class="text-sm">暂无知识库</p>
          <p class="text-xs mt-1">点击"新建知识库"创建第一个文献库</p>
        </div>

        <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="kb in adminStore.knowledgeBases"
            :key="kb.id"
            class="group relative rounded-xl border bg-white p-5 shadow-sm transition-all hover:shadow-md cursor-pointer"
            @click="goToKB(kb.id)"
          >
            <!-- KB card content -->
            <div class="flex items-start gap-3">
              <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-50">
                <BookOpen :size="18" class="text-primary-600" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5">
                  <h3 class="text-sm font-semibold text-slate-800 truncate">{{ kb.name }}</h3>
                  <span
                    v-if="kb.slug === 'zhong_guo_quan_ke'"
                    class="inline-flex shrink-0 items-center rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600 border border-primary-200"
                  >默认</span>
                  <ShieldCheck
                    v-if="kb.has_ready_docs"
                    :size="13"
                    class="shrink-0 text-emerald-500"
                    title="已有就绪文档"
                  />
                </div>
                <p class="mt-1 text-xs text-slate-500 line-clamp-2">{{ kb.description || '暂无描述' }}</p>
              </div>
            </div>

            <!-- Footer -->
            <div class="mt-4 flex items-center justify-between border-t pt-3">
              <div class="flex items-center gap-3 text-xs text-slate-400">
                <span>{{ kb.document_count }} 篇文献</span>
                <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                  :class="kb.has_ready_docs ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'"
                >
                  {{ kb.has_ready_docs ? '只读' : '可上传' }}
                </span>
              </div>
              <div class="flex items-center gap-1">
                <button
                  v-if="adminStore.activeKbId !== kb.id"
                  class="inline-flex items-center gap-1 rounded-lg border border-primary-200 bg-primary-50 px-2.5 py-1 text-[11px] font-medium text-primary-600 opacity-0 group-hover:opacity-100 hover:bg-primary-100 transition-all shrink-0"
                  @click.stop="activateKb(kb)"
                >启用此知识库</button>
                <span
                  v-else
                  class="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-600 shrink-0"
                >当前使用中 ✓</span>
                <button
                  v-if="kb.slug !== 'zhong_guo_quan_ke'"
                  class="flex h-7 w-7 items-center justify-center rounded text-slate-300 opacity-0 hover:bg-red-50 hover:text-red-500 transition-all group-hover:opacity-100"
                  @click.stop="handleDelete(kb.id)"
                >
                  <Trash2 :size="14" />
                </button>
                <ArrowRight :size="14" class="text-slate-300 opacity-0 group-hover:opacity-100 transition-all" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Create Modal -->
      <Teleport to="body">
        <Transition name="fade">
          <div
            v-if="showCreateModal"
            class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
            @click.self="showCreateModal = false"
          >
            <div class="w-full max-w-md rounded-2xl border bg-white p-6 shadow-xl">
              <h2 class="text-lg font-semibold text-slate-800 mb-4">新建知识库</h2>

              <div class="mb-4">
                <label class="mb-1.5 block text-sm font-medium text-slate-700">名称</label>
                <input
                  v-model="newName"
                  placeholder="如：心血管专科文献库"
                  class="w-full rounded-xl border bg-slate-50 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                  @keydown.enter="handleCreate"
                />
              </div>

              <div class="mb-4">
                <label class="mb-1.5 block text-sm font-medium text-slate-700">英文标识</label>
                <input
                  v-model="newSlug"
                  placeholder="如：cardio（仅小写字母数字下划线）"
                  class="w-full rounded-xl border bg-slate-50 px-3 py-2 text-sm font-mono outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                  @keydown.enter="handleCreate"
                />
                <p class="mt-1 text-[11px] text-slate-400">用于 ES 索引和 Milvus 集合命名</p>
              </div>

              <div class="mb-6">
                <label class="mb-1.5 block text-sm font-medium text-slate-700">描述（选填）</label>
                <textarea
                  v-model="newDesc"
                  rows="2"
                  placeholder="简要描述知识库内容..."
                  class="w-full rounded-xl border bg-slate-50 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100 resize-none"
                />
              </div>

              <div class="flex justify-end gap-3">
                <button
                  class="rounded-lg px-4 py-2 text-sm text-slate-500 hover:bg-slate-100 transition-colors"
                  @click="showCreateModal = false"
                >取消</button>
                <button
                  :disabled="creating || !newName.trim() || !newSlug.trim()"
                  class="rounded-lg bg-primary-600 px-5 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-40 transition-colors"
                  @click="handleCreate"
                >
                  {{ creating ? '创建中...' : '创建' }}
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </Teleport>
    </div>
  </AppLayout>
</template>
