import { get, post, put, del } from './request'
import type {
  ConversationCreate,
  ConversationUpdate,
  Conversation,
  ConversationListResponse,
  MessageListResponse,
} from '@/types'

export function listConversationsApi(
  kbId: number,
  page = 1,
  pageSize = 20,
  search?: string,
  startDate?: string,
  endDate?: string,
) {
  const params: Record<string, unknown> = { kb_id: kbId, page, page_size: pageSize }
  if (search) params.q = search
  if (startDate) params.start_date = startDate
  if (endDate) params.end_date = endDate
  return get<ConversationListResponse>('/conversations', params)
}

export function createConversationApi(data: ConversationCreate) {
  return post<Conversation>('/conversations', data as unknown as Record<string, unknown>)
}

export function getConversationApi(convId: number) {
  return get<Conversation>(`/conversations/${convId}`)
}

export function updateConversationApi(convId: number, data: ConversationUpdate) {
  return put<Conversation>(`/conversations/${convId}`, data as unknown as Record<string, unknown>)
}

export function pinConversationApi(convId: number, isPinned: boolean) {
  return put<Conversation>(`/conversations/${convId}`, { is_pinned: isPinned } as unknown as Record<string, unknown>)
}

export function starConversationApi(convId: number, isStarred: boolean) {
  return put<Conversation>(`/conversations/${convId}`, { is_starred: isStarred } as unknown as Record<string, unknown>)
}

export function deleteConversationApi(convId: number) {
  return del(`/conversations/${convId}`)
}

export function regenerateMessageApi(convId: number, msgId: number, editedQuestion: string) {
  return post(`/conversations/${convId}/messages/${msgId}/regenerate`, undefined, { params: { edited_question: editedQuestion } })
}

export function forkConversationApi(convId: number, messageId: number) {
  return post<{ forked_from: number; new_conversation_id: number; copied_messages: number }>(
    `/conversations/${convId}/fork`, undefined, { params: { message_id: messageId } },
  )
}

export function getMessagesApi(convId: number, beforeId?: number, limit = 50) {
  const params: Record<string, unknown> = { limit }
  if (beforeId !== undefined) {
    params.before_id = beforeId
  }
  return get<MessageListResponse>(`/conversations/${convId}/messages`, params)
}

export async function downloadConversation(convId: number, format: 'md' | 'pdf' = 'md', title: string = 'conversation'): Promise<void> {
  const token = sessionStorage.getItem('access_token') || ''
  const base = '/api/v1'
  const url = `${base}/conversations/${convId}/export?format=${format}`
  const resp = await fetch(url, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
  })
  if (!resp.ok) throw new Error(`Export failed: ${resp.status}`)
  const blob = await resp.blob()
  const blobUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = `${title.slice(0, 30)}.md`
  a.click()
  URL.revokeObjectURL(blobUrl)
}

