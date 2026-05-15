import api from './index'
import type { SystemUser } from '@/types'

export function fetchUsersApi(): Promise<SystemUser[]> {
  return api.get('/admin/users').then((res) => res.data)
}

export function toggleUserStatusApi(id: string, enabled: boolean): Promise<void> {
  return api.patch(`/admin/users/${id}`, { enabled }).then((res) => res.data)
}
