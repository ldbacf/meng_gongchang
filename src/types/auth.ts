export interface LoginRequest {
  username: string
  password: string
}

export interface User {
  username: string
  role: 'admin' | 'user'
}

export interface LoginResponse {
  token: string
  user: User
}
