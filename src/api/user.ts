import api from './index'
import type { SystemUser } from '@/types'
import { USE_MOCK, mockUsers, simulateDelay } from '@/mock'

export async function fetchUsersApi(): Promise<SystemUser[]> {
  if (USE_MOCK) {
    await simulateDelay(150)
    return [...mockUsers]
  }
  return api.get('/admin/users').then((res) => res.data)
}

export async function toggleUserStatusApi(id: string, enabled: boolean): Promise<void> {
  if (USE_MOCK) {
    await simulateDelay(100)
    return
  }
  return api.patch(`/admin/users/${id}`, { enabled }).then((res) => res.data)
}
