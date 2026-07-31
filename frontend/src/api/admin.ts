/**
 * Phase 10: 管理后台 API
 */
import { get, patch } from './request'

export interface AdminUserItem {
  id: number
  username: string
  email: string
  system_role: string
  is_active: boolean
  created_at: string
}

export function listUsersApi(page = 1, pageSize = 20, query?: string, role?: string) {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (query) params.q = query
  if (role) params.role = role
  return get<{ items: AdminUserItem[]; total: number }>('/admin/users', params)
}

export function updateUserRoleApi(userId: number, role: string) {
  return patch(`/admin/users/${userId}/role`, undefined, { params: { role } })
}

export interface AuditLogItem {
  id: number
  user_id: number
  action: string
  resource_type: string
  resource_id: number
  details: Record<string, unknown>
  ip_address: string
  created_at: string
}

export function listAuditLogsApi(params: {
  page?: number; page_size?: number; user_id?: number; action?: string
  resource_type?: string; start_date?: string; end_date?: string
} = {}) {
  return get<{ items: AuditLogItem[]; total: number }>('/admin/audit-logs', params as Record<string, unknown>)
}

export interface AdminStats {
  user_count: number
  kb_count: number
  document_count: number
  conversation_count: number
  llm_provider: string
  app_version: string
}

export function getAdminStatsApi() {
  return get<AdminStats>('/admin/stats')
}

export interface LLMCostStats {
  daily: { used: number; limit: number; input_tokens: number; output_tokens: number; requests: number }
  monthly: { used: number; limit: number; input_tokens: number; output_tokens: number; requests: number }
  provider: string
}

export function getLLMCostApi() {
  return get<LLMCostStats>('/admin/llm-cost')
}

export interface ConfigItem {
  key: string
  value: string
  description: string
  updated_at: string
}

export function getSystemConfigApi() {
  return get<{ items: ConfigItem[]; static_config: Record<string, unknown> }>('/admin/system-config')
}

export function updateSystemConfigApi(key: string, value: string) {
  return patch(`/admin/system-config/${key}`, undefined, { params: { value } })
}
