import { get, post, put, del, patch } from './request'
import type { KnowledgeBase, KBCreate, KBUpdate, KBStats } from '@/types'

export function createKBApi(data: KBCreate) {
  return post<KnowledgeBase>('/knowledge-bases', data as unknown as Record<string, unknown>)
}

export function listKBsApi(page = 1, pageSize = 20) {
  return get<{ items: KnowledgeBase[]; total: number; page: number; page_size: number }>(
    '/knowledge-bases',
    { page, page_size: pageSize }
  )
}

export function getKBApi(kbId: number) {
  return get<KnowledgeBase>(`/knowledge-bases/${kbId}`)
}

export function updateKBApi(kbId: number, data: KBUpdate) {
  return put<KnowledgeBase>(`/knowledge-bases/${kbId}`, data as unknown as Record<string, unknown>)
}

export function deleteKBApi(kbId: number) {
  return del(`/knowledge-bases/${kbId}`)
}

export function getKBStatsApi(kbId: number) {
  return get<KBStats>(`/knowledge-bases/${kbId}/stats`)
}

export function updateAgentConfigApi(kbId: number, systemPrompt: string) {
  return patch<{ kb_id: number; system_prompt: string | null }>(`/knowledge-bases/${kbId}/agent-config`, {
    system_prompt: systemPrompt,
  } as unknown as Record<string, unknown>)
}
