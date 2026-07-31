import { post, get, del } from './request'
import type { LoginRequest, RegisterRequest, TokenResponse, UserInfo, APIKeyInfo } from '@/types'

export const loginApi = (data: LoginRequest) =>
  post<TokenResponse>('/auth/login', data as unknown as Record<string, unknown>)

export const registerApi = (data: RegisterRequest) =>
  post<UserInfo>('/auth/register', data as unknown as Record<string, unknown>)

export const refreshApi = (refreshToken: string, currentAccessToken?: string) =>
  post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken, current_access_token: currentAccessToken })

export const logoutApi = () => post('/auth/logout')

export const getUserInfoApi = () => get<UserInfo>('/auth/me')

export const generateApiKeyApi = () => post<{ api_key: string; prefix: string; expires_at: string }>('/auth/api-key')

export const revokeApiKeyApi = () => del('/auth/api-key')

export const getApiKeyInfoApi = () => get<APIKeyInfo>('/auth/api-key/info')
