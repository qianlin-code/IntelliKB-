import { get, post } from './request'

export interface EvalRun {
  id: number
  kb_id: number
  provider: string
  rewrite_strategy: string | null
  query_count: number
  hit_rate_at_3: number
  hit_rate_at_5: number
  mrr: number
  recall_at_5: number
  created_at: string
}

export interface BadcaseItem {
  id: number
  question: string
  expected_doc_ids: string
  retrieved_chunk_ids: string
  latency_ms: number
}

export function synthesizeQueries(kbId: number, count = 50) {
  return post<{ generated: number }>('/eval/queries/synthesize', undefined, { params: { kb_id: kbId, count } })
}

export function runEval(kbId: number, topK = 5, provider?: string, strategy?: string) {
  const params: Record<string, string | number> = { kb_id: kbId, top_k: topK }
  if (provider) params.provider = provider
  if (strategy) params.strategy = strategy
  return post<EvalRun>('/eval/run', undefined, { params })
}

export function listEvalRuns(kbId: number, page = 1, pageSize = 20) {
  return get<{ items: EvalRun[] }>('/eval/runs', { params: { kb_id: kbId, page, page_size: pageSize } })
}

export function listBadcases(runId: number) {
  return get<{ items: BadcaseItem[] }>(`/eval/runs/${runId}/badcases`)
}
