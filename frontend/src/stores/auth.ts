import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserResponse } from '@/types'
import { loginApi, refreshApi, fetchMeApi, logoutApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<UserResponse | null>(JSON.parse(localStorage.getItem('user') ?? 'null'))

  const isAdmin = computed(() => user.value?.role === 'admin')
  const isAuthenticated = computed(() => !!accessToken.value)

  async function login(username: string, password: string) {
    const res = await loginApi({ username, password })
    accessToken.value = res.access_token
    refreshToken.value = res.refresh_token
    user.value = res.user
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    localStorage.setItem('user', JSON.stringify(res.user))
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) throw new Error('No refresh token')
    const res = await refreshApi({ refresh_token: refreshToken.value })
    accessToken.value = res.access_token
    refreshToken.value = res.refresh_token
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
  }

  async function validateSession(): Promise<boolean> {
    if (!accessToken.value) return false
    try {
      const me = await fetchMeApi()
      user.value = me
      localStorage.setItem('user', JSON.stringify(me))
      return true
    } catch {
      try {
        await refreshAccessToken()
        const me = await fetchMeApi()
        user.value = me
        return true
      } catch {
        logout()
        return false
      }
    }
  }

  function logout() {
    const rt = refreshToken.value
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    if (rt) {
      logoutApi(rt).catch(() => {})
    }
  }

  return { accessToken, refreshToken, user, isAdmin, isAuthenticated, login, logout, validateSession, refreshAccessToken }
})
