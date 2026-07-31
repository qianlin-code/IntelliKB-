import { post } from './request'
import type { SearchRequest, SearchResponse, AskRequest, AskResponse } from '@/types'

export function searchChunksApi(data: SearchRequest) {
  return post<SearchResponse>('/qa/search', data as unknown as Record<string, unknown>)
}

export function askQuestionApi(data: AskRequest) {
  return post<AskResponse>('/qa/ask', data as unknown as Record<string, unknown>)
}

/**
 * Phase P0: RAG SSE 流式问答（POST body）。
 *
 * 解决 GET /qa/ask-stream URL 长度限制问题。
 */
export function buildAskStreamPayload(data: AskRequest): Record<string, unknown> {
  return {
    kb_id: data.kb_id,
    question: data.question,
    top_k: data.top_k ?? 5,
    conversation_id: data.conversation_id ?? null,
  }
}
