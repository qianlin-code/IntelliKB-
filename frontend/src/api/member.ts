import { get, post, put, del } from './request'
import type { MemberInfo, MemberAdd, MemberUpdate } from '@/types'

export function listMembersApi(kbId: number) {
  return get<{ members: MemberInfo[] }>(`/knowledge-bases/${kbId}/members`)
}

export function addMemberApi(kbId: number, data: MemberAdd) {
  return post<MemberInfo>(`/knowledge-bases/${kbId}/members`, data as unknown as Record<string, unknown>)
}

export function updateMemberApi(kbId: number, userId: number, data: MemberUpdate) {
  return put<MemberInfo>(`/knowledge-bases/${kbId}/members/${userId}`, data as unknown as Record<string, unknown>)
}

export function removeMemberApi(kbId: number, userId: number) {
  return del(`/knowledge-bases/${kbId}/members/${userId}`)
}
