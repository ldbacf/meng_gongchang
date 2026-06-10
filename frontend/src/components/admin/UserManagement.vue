<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Shield, ShieldOff, Circle } from 'lucide-vue-next'
import { useAdminStore } from '@/stores/admin'

const adminStore = useAdminStore()

onMounted(() => {
  adminStore.fetchUsers()
})

function formatTime(ts: number): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-6 py-4">
      <div>
        <h1 class="text-lg font-semibold text-slate-800">用户管理</h1>
        <p class="text-sm text-slate-500">管理系统用户及访问权限</p>
      </div>
    </div>

    <!-- User Table -->
    <div class="flex-1 overflow-y-auto p-6">
      <div class="overflow-hidden rounded-xl border bg-white">
        <table class="w-full">
          <thead>
            <tr class="border-b bg-slate-50/80">
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                用户名
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                角色
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                最后登录
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                状态
              </th>
              <th class="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in adminStore.users"
              :key="user.id"
              class="border-b last:border-b-0 hover:bg-slate-50/50 transition-colors"
            >
              <td class="px-4 py-3 text-sm font-medium text-slate-800">
                {{ user.username }}
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="
                    user.role === 'admin'
                      ? 'bg-purple-50 text-purple-700'
                      : 'bg-slate-100 text-slate-600'
                  "
                >
                  <Circle :size="6" class="fill-current" />
                  {{ user.role === 'admin' ? '管理员' : '用户' }}
                </span>
              </td>
              <td class="px-4 py-3 text-sm text-slate-500">
                {{ formatTime(user.lastLogin) }}
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="
                    user.enabled
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-red-50 text-red-600'
                  "
                >
                  <Circle :size="6" class="fill-current" />
                  {{ user.enabled ? '启用' : '禁用' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                  :class="
                    user.enabled
                      ? 'text-red-600 hover:bg-red-50'
                      : 'text-emerald-600 hover:bg-emerald-50'
                  "
                  @click="adminStore.toggleUserStatus(user.id)"
                >
                  <ShieldOff v-if="user.enabled" :size="14" />
                  <Shield v-else :size="14" />
                  {{ user.enabled ? '禁用' : '启用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div
          v-if="adminStore.users.length === 0"
          class="flex items-center justify-center py-16 text-sm text-slate-400"
        >
          暂无用户数据
        </div>
      </div>
    </div>
  </div>
</template>
