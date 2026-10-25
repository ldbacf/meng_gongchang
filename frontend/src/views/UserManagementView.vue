<script setup lang="ts">
/**
 * 用户管理页。
 *
 * 实际表格在 `components/admin/UserManagement.vue`，这里只补页面级页头；
 * 外壳（后台左侧导航）由父路由 `AdminLayout` 提供。
 */
import { computed } from 'vue'
import { useAdminStore } from '@/stores/admin'
import UserManagement from '@/components/admin/UserManagement.vue'

const adminStore = useAdminStore()

const stats = computed(() => ({
  total: adminStore.users.length,
  admin: adminStore.users.filter((u) => u.role === 'admin').length,
}))
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <div class="border-b border-line px-8 pb-5 pt-6">
      <h1 class="text-[22px] font-semibold tracking-[-.3px]">用户管理</h1>
      <p class="mt-1 text-[13px] text-muted">
        共 <b class="font-semibold text-ink-2">{{ stats.total }}</b> 个账号 ·
        管理员 <b class="font-semibold text-ink-2">{{ stats.admin }}</b>
      </p>
    </div>

    <div class="flex-1 overflow-hidden">
      <UserManagement />
    </div>
  </div>
</template>
