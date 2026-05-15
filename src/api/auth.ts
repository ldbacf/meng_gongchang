import api from './index'
import type { LoginRequest, LoginResponse } from '@/types'

export function loginApi(data: LoginRequest): Promise<LoginResponse> {
  return api.post('/auth/login', data).then((res) => res.data)
}
