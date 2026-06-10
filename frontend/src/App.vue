<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import ToastContainer from '@/components/common/ToastContainer.vue'
import { RouterView } from 'vue-router'

const router = useRouter()
const authStore = useAuthStore()
const toastStore = useToastStore()

onMounted(async () => {
  if (authStore.isAuthenticated) {
    const valid = await authStore.validateSession()
    if (!valid) {
      toastStore.error('登录已过期，请重新登录')
      router.push('/login')
    }
  }
})

// Global error handler
window.addEventListener('unhandledrejection', (event) => {
  const msg = event.reason?.message || String(event.reason)
  if (msg.includes('Failed to fetch')) {
    toastStore.error('网络连接失败，请检查后端服务')
  } else if (!msg.includes('AbortError')) {
    toastStore.error(msg)
  }
})
</script>

<template>
  <RouterView />
  <ToastContainer />
</template>
