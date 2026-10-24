<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { Shield, ShieldOff, Search } from 'lucide-vue-next'
import { useAdminStore } from '@/stores/admin'

const adminStore = useAdminStore()
const keyword = ref('')

onMounted(() => {
  adminStore.fetchUsers()
})

function formatTime(ts: number): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN')
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return adminStore.users
  return adminStore.users.filter((u) => u.username.toLowerCase().includes(k))
})

const stats = computed(() => ({
  total: adminStore.users.length,
  admin: adminStore.users.filter((u) => u.role === 'admin').length,
  disabled: adminStore.users.filter((u) => !u.enabled).length,
}))
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- 页头 -->
    <div class="border-b border-line px-8 pb-5 pt-2">
      <h1 class="text-[22px] font-semibold tracking-[-.3px]">用户管理</h1>
      <p class="mt-1 text-[13px] text-muted">管理系统用户、角色与访问权限</p>

      <div class="mt-5 flex flex-wrap items-center gap-2.5">
        <span class="rounded-full border border-line bg-surface-2 px-3 py-1 text-[12px] text-ink-2">
          共 <b class="font-semibold text-ink">{{ stats.total }}</b> 个用户
        </span>
        <span class="rounded-full border border-line bg-surface-2 px-3 py-1 text-[12px] text-ink-2">
          管理员 <b class="font-semibold text-ink">{{ stats.admin }}</b>
        </span>
        <span
          v-if="stats.disabled"
          class="rounded-full border border-line bg-warn-soft px-3 py-1 text-[12px] text-warn"
        >
          待审核/禁用 <b class="font-semibold">{{ stats.disabled }}</b>
        </span>

        <div class="relative ml-auto">
          <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            v-model="keyword"
            placeholder="搜索用户名"
            class="w-[210px] rounded-full border border-line bg-surface-2 py-1.5 pl-8 pr-3 text-[12.5px] text-ink placeholder:text-faint outline-none transition-colors focus:border-accent"
          />
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="flex-1 overflow-y-auto px-8 py-5">
      <div class="overflow-hidden rounded-xl border border-line bg-surface-2">
        <table class="w-full">
          <thead>
            <tr class="border-b border-line bg-surface">
              <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[.4px] text-faint">用户名</th>
              <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[.4px] text-faint">角色</th>
              <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[.4px] text-faint">最后登录</th>
              <th class="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[.4px] text-faint">状态</th>
              <th class="px-4 py-2.5 text-right text-[11px] font-semibold uppercase tracking-[.4px] text-faint">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in filtered"
              :key="user.id"
              class="border-b border-line transition-colors last:border-b-0 hover:bg-surface"
            >
              <td class="px-4 py-3">
                <div class="flex items-center gap-2.5">
                  <div
                    class="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10.5px] font-semibold text-white"
                    style="background: linear-gradient(100deg, var(--grad-1), var(--grad-2), var(--grad-3))"
                  >
                    {{ user.username.slice(0, 1).toUpperCase() }}
                  </div>
                  <span class="text-[13.5px] font-medium">{{ user.username }}</span>
                </div>
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium"
                  :class="user.role === 'admin' ? 'bg-accent-soft text-accent-text' : 'bg-surface text-muted'"
                >
                  {{ user.role === 'admin' ? '管理员' : '用户' }}
                </span>
              </td>
              <td class="px-4 py-3 font-mono text-[12px] tabular-nums text-muted">
                {{ formatTime(user.lastLogin) }}
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11.5px] font-medium"
                  :class="user.enabled ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger'"
                >
                  <span class="h-1.5 w-1.5 rounded-full bg-current" />
                  {{ user.enabled ? '已启用' : '待审核' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  class="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors"
                  :class="
                    user.enabled
                      ? 'text-danger hover:bg-danger-soft'
                      : 'text-ok hover:bg-ok-soft'
                  "
                  @click="adminStore.toggleUserStatus(user.id)"
                >
                  <ShieldOff v-if="user.enabled" :size="13" />
                  <Shield v-else :size="13" />
                  {{ user.enabled ? '禁用' : '通过审核' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-if="filtered.length === 0"
          class="flex items-center justify-center py-16 text-[12.5px] text-faint"
        >
          {{ keyword ? '没有匹配的用户' : '暂无用户数据' }}
        </div>
      </div>
    </div>
  </div>
</template>
