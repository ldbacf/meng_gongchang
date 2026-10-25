<script setup lang="ts">
/**
 * 后台管理 — 聚合页。
 *
 * 原先「知识库管理 / 用户管理」是侧栏里两个常驻入口，占空间且只对管理员有意义。
 * 现在统一收到这里：侧栏只留头像菜单里的「设置」，点进来就是本页，用 tab 切换。
 *
 * 用 query `?tab=users|knowledge` 记录页签，刷新/收藏链接都能还原。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Database, Users } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'
import UserManagement from '@/components/admin/UserManagement.vue'

const route = useRoute()
const router = useRouter()

type TabKey = 'knowledge' | 'users'

const TABS = [
  { key: 'knowledge' as TabKey, label: '知识库管理', icon: Database },
  { key: 'users' as TabKey, label: '用户管理', icon: Users },
]

const activeTab = computed<TabKey>(() => (route.query.tab === 'users' ? 'users' : 'knowledge'))

function switchTab(key: TabKey) {
  router.replace({ path: '/admin', query: { tab: key } })
}
</script>

<template>
  <AppLayout>
    <div class="flex h-full flex-col overflow-hidden">
      <!-- 页头 + 页签 -->
      <div class="border-b border-line px-8 pt-3">
        <h1 class="text-[22px] font-semibold tracking-[-.3px]">后台管理</h1>
        <p class="mt-1 text-[13px] text-muted">知识库与用户账号的集中管理</p>

        <div class="mt-3 flex items-center gap-1">
          <button
            v-for="t in TABS"
            :key="t.key"
            class="relative flex items-center gap-2 px-3.5 pb-2.5 pt-2 text-[13.5px] transition-colors"
            :class="
              activeTab === t.key
                ? 'font-medium text-accent-text'
                : 'text-muted hover:text-ink'
            "
            @click="switchTab(t.key)"
          >
            <component :is="t.icon" :size="15" />
            {{ t.label }}
            <span
              v-if="activeTab === t.key"
              class="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-accent"
            />
          </button>
        </div>
      </div>

      <!-- 子页面：嵌入模式（不再套外壳、不重复标题） -->
      <div class="flex-1 overflow-hidden">
        <KnowledgeBaseView v-if="activeTab === 'knowledge'" embedded />
        <UserManagement v-else />
      </div>
    </div>
  </AppLayout>
</template>
