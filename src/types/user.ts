export interface SystemUser {
  id: string
  username: string
  role: 'admin' | 'user'
  lastLogin: number
  enabled: boolean
}
