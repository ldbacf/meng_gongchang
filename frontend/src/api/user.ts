import api from './index'
import type { SystemUser } from '@/types'

export async function fetchUsersApi(): Promise<SystemUser[]> {
  return api.get('/v1/admin/users').then((res) =>
    (res.data as any[]).map((u: any) => ({
      id: u.id,
      username: u.username,
      role: u.role,
      lastLogin: u.last_login ? new Date(u.last_login).getTime() : 0,
      enabled: u.enabled,
    })),
  )
}

export async function toggleUserStatusApi(id: string, enabled: boolean): Promise<void> {
  return api.patch(`/v1/admin/users/${id}`, { enabled })
}

export async function createUserApi(data: { username: string; password: string; role: string }): Promise<SystemUser> {
  return api.post('/v1/admin/users', data).then((res) => {
    const u = res.data
    return { id: u.id, username: u.username, role: u.role, lastLogin: 0, enabled: u.enabled }
  })
}

export async function deleteUserApi(id: string): Promise<void> {
  return api.delete(`/v1/admin/users/${id}`)
}
