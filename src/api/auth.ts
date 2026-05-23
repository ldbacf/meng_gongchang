import api from './index'
import type { LoginRequest, LoginResponse, TokenRefreshRequest, TokenRefreshResponse, UserResponse } from '@/types'

export async function loginApi(data: LoginRequest): Promise<LoginResponse> {
  return api.post('/v1/auth/login', data).then((res) => res.data)
}

export async function refreshApi(data: TokenRefreshRequest): Promise<TokenRefreshResponse> {
  return api.post('/v1/auth/refresh', data).then((res) => res.data)
}

export async function fetchMeApi(): Promise<UserResponse> {
  return api.get('/v1/auth/me').then((res) => res.data)
}

export async function logoutApi(refreshToken?: string): Promise<void> {
  return api.post('/v1/auth/logout', { refresh_token: refreshToken ?? null })
}
