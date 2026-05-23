import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export function useAuth() {
  const store = useAuthStore()
  const router = useRouter()

  const isAdmin = computed(() => store.user?.role === 'admin')
  const isAuthenticated = computed(() => !!store.accessToken)

  function requireAuth(): boolean {
    if (!store.accessToken) {
      router.push('/login')
      return false
    }
    return true
  }

  function requireAdmin(): boolean {
    if (!store.accessToken) {
      router.push('/login')
      return false
    }
    if (store.user?.role !== 'admin') {
      router.push('/chat')
      return false
    }
    return true
  }

  function logout() {
    store.logout()
    router.push('/login')
  }

  return { isAdmin, isAuthenticated, requireAuth, requireAdmin, logout }
}
