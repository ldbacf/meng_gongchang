<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { useToastStore } from '@/stores/toast'
import { Plus, BookOpen, Trash2, ArrowRight, Lock, Check } from 'lucide-vue-next'

// 外壳（后台左侧导航）由父路由 AdminLayout 提供，这里只渲染内容。
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

const totalDocs = computed(() =>
  adminStore.knowledgeBases.reduce((n, kb) => n + (kb.document_count ?? 0), 0),
)

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
  <div class="flex h-full flex-col overflow-hidden">
    <!-- 页头 -->
    <div class="border-b border-line px-8 pb-5 pt-6">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-[22px] font-semibold tracking-[-.3px]">知识库管理</h1>
          <p class="mt-1 text-[13px] text-muted">
            每个知识库独立建索引与检索；共
            <b class="font-semibold text-ink-2">{{ adminStore.knowledgeBases.length }}</b> 个库 ·
            <b class="font-semibold text-ink-2">{{ totalDocs }}</b> 篇文献
          </p>
        </div>
        <button
          class="flex shrink-0 items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover"
          @click="openCreate"
        >
          <Plus :size="15" />
          新建知识库
        </button>
      </div>
    </div>

    <!-- 卡片网格 -->
    <div class="flex-1 overflow-y-auto px-8 py-5">
      <!-- 骨架 -->
      <div v-if="adminStore.kbLoading" class="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="i in 3" :key="i" class="rounded-xl border border-line bg-surface-2 p-5">
          <div class="skeleton mb-3 h-4 w-28" />
          <div class="skeleton mb-2 h-3 w-full" />
          <div class="skeleton h-3 w-3/4" />
        </div>
      </div>

      <!-- 空 -->
      <div
        v-else-if="adminStore.knowledgeBases.length === 0"
        class="flex flex-col items-center justify-center py-24 text-faint"
      >
        <BookOpen :size="34" class="mb-3 opacity-60" />
        <p class="text-[13px]">暂无知识库</p>
        <p class="mt-1 text-[12px]">点击「新建知识库」创建第一个文献库</p>
      </div>

      <!-- 列表 -->
      <div v-else class="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="kb in adminStore.knowledgeBases"
          :key="kb.id"
          class="group relative cursor-pointer rounded-xl border border-line bg-surface-2 p-4 transition-all hover:border-line-strong hover:shadow-sm"
          :class="{ 'border-accent': adminStore.activeKbId === kb.id }"
          @click="goToKB(kb.id)"
        >
          <div class="flex items-start gap-3">
            <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft">
              <BookOpen :size="17" class="text-accent-text" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <h3 class="truncate text-[13.5px] font-semibold">{{ kb.name }}</h3>
                <span
                  v-if="kb.slug === 'zhong_guo_quan_ke'"
                  class="shrink-0 rounded-full bg-accent-soft px-1.5 py-px text-[10px] font-medium text-accent-text"
                >默认</span>
                <Lock v-if="kb.has_ready_docs" :size="11" class="shrink-0 text-faint" title="已有就绪文档" />
              </div>
              <p class="mt-1 line-clamp-2 text-[12px] leading-relaxed text-muted">
                {{ kb.description || '暂无描述' }}
              </p>
            </div>
          </div>

          <div class="mt-3.5 flex items-center justify-between border-t border-line pt-3">
            <div class="flex items-center gap-2 text-[11.5px] text-faint">
              <span>{{ kb.document_count }} 篇</span>
              <span
                class="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                :class="kb.has_ready_docs ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'"
              >
                {{ kb.has_ready_docs ? '只读' : '可上传' }}
              </span>
            </div>

            <div class="flex items-center gap-1">
              <span
                v-if="adminStore.activeKbId === kb.id"
                class="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-[10.5px] font-medium text-ok"
                title="对话检索的是这个库"
              >
                <Check :size="10" />
                对话使用中
              </span>
              <!-- 切换活跃库必须**始终可见**。
                   原先这个按钮是 `opacity-0` + `group-hover:opacity-100`，结果：
                   用户进详情页浏览新库时根本不会发现要点「启用」切换，回到对话
                   仍在检索上一个库。表现为「换成了其他知识库，对话还是医学相关」。
                   注意卡片本身点击是「进入详情」（goToKB），不是切换。 -->
              <button
                v-else
                class="rounded-full border border-line px-2.5 py-0.5 text-[10.5px] font-medium text-ink-2 transition-colors hover:bg-surface hover:border-line-strong"
                title="让对话检索这个知识库"
                @click.stop="activateKb(kb)"
              >设为对话库</button>

              <button
                v-if="kb.slug !== 'zhong_guo_quan_ke'"
                class="grid h-6 w-6 place-items-center rounded-full text-faint opacity-0 transition-all hover:bg-danger-soft hover:text-danger group-hover:opacity-100"
                title="删除"
                @click.stop="handleDelete(kb.id)"
              >
                <Trash2 :size="12" />
              </button>
              <ArrowRight :size="13" class="text-faint opacity-0 transition-all group-hover:opacity-100" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showCreateModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
          @click.self="showCreateModal = false"
        >
          <div class="w-full max-w-[440px] rounded-2xl border border-line bg-surface-2 p-6 shadow-lg">
            <h2 class="mb-5 text-[16px] font-semibold">新建知识库</h2>

            <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">名称</label>
            <input
              v-model="newName"
              placeholder="如：心血管专科文献库"
              class="mb-4 w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] outline-none transition-colors focus:border-accent focus:bg-canvas"
              @keydown.enter="handleCreate"
            />

            <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">英文标识</label>
            <input
              v-model="newSlug"
              placeholder="如：cardio"
              class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 font-mono text-[13px] outline-none transition-colors focus:border-accent focus:bg-canvas"
              @keydown.enter="handleCreate"
            />
            <p class="mb-4 mt-1.5 text-[11px] text-faint">用于 ES 索引与 Milvus 集合命名，仅小写字母、数字、下划线</p>

            <label class="mb-1.5 block text-[12.5px] font-medium text-ink-2">描述（选填）</label>
            <textarea
              v-model="newDesc"
              rows="2"
              placeholder="简要描述知识库内容…"
              class="mb-6 w-full resize-none rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] outline-none transition-colors focus:border-accent focus:bg-canvas"
            />

            <div class="flex justify-end gap-2">
              <button
                class="rounded-full px-4 py-2 text-[13px] text-muted transition-colors hover:bg-surface"
                @click="showCreateModal = false"
              >取消</button>
              <button
                :disabled="creating || !newName.trim() || !newSlug.trim()"
                class="rounded-full bg-accent px-5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
                @click="handleCreate"
              >
                {{ creating ? '创建中…' : '创建' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
