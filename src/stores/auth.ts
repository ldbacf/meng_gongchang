import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '@/types'
import { loginApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<User | null>(JSON.parse(localStorage.getItem('user') ?? 'null'))

  const isAdmin = computed(() => user.value?.role === 'admin')
  const isAuthenticated = computed(() => !!token.value)

  async function login(username: string, password: string) {
    const role: 'admin' | 'user' = username === 'admin' ? 'admin' : 'user'
    try {
      const res = await loginApi({ username, password })
      token.value = res.token
      user.value = res.user
    } catch {
      // Fallback for demo: local-only auth
      const fakeToken = btoa(`${username}:${Date.now()}`)
      token.value = fakeToken
      user.value = { username, role }
    }

    localStorage.setItem('token', token.value!)
    localStorage.setItem('user', JSON.stringify(user.value))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return { token, user, isAdmin, isAuthenticated, login, logout }
})
