import api from './index'
import type { LoginRequest, LoginResponse } from '@/types'
import { USE_MOCK, mockLoginResponse, simulateDelay } from '@/mock'

export async function loginApi(data: LoginRequest): Promise<LoginResponse> {
  if (USE_MOCK) {
    await simulateDelay(300)
    return {
      ...mockLoginResponse,
      user: { username: data.username, role: data.username === 'admin' ? 'admin' : 'user' },
    }
  }
  return api.post('/auth/login', data).then((res) => res.data)
}
