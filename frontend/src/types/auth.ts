export interface LoginRequest {
  username: string
  password: string
}

export interface UserResponse {
  id: string
  username: string
  role: 'admin' | 'user'
  enabled: boolean
  last_login: string | null
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserResponse
}

export interface TokenRefreshRequest {
  refresh_token: string
}

export interface TokenRefreshResponse {
  access_token: string
  refresh_token: string
  token_type: string
}
