export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  trace_id: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  email?: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: number
  username: string
  email: string | null
  is_active: boolean
  api_key_enabled: boolean
  api_key_prefix: string | null
  api_key_expires_at: string | null
  created_at: string
}

export interface APIKeyInfo {
  prefix: string | null
  expires_at: string | null
  last_used_at: string | null
  enabled: boolean
}

// ── Phase 1: 知识库 ──
export interface KnowledgeBase {
  id: number; owner_id: number; name: string; description: string | null
  is_public: boolean; chunk_size: number; chunk_overlap: number
  embedding_model: string; created_at: string; updated_at: string
}
export interface KBCreate { name: string; description?: string; is_public?: boolean; chunk_size?: number; chunk_overlap?: number }
export interface KBUpdate { name?: string; description?: string; is_public?: boolean; chunk_size?: number; chunk_overlap?: number }
export interface KBStats { kb_id: number; document_count: number; chunk_count: number; total_size_bytes: number }

// ── Phase 1: 文档 ──
export interface DocumentInfo { id: number; kb_id: number; filename: string; file_type: string; file_size: number; status: string; chunk_count: number; error_message: string | null; created_at: string; updated_at: string }
export interface DocumentUploadResponse { doc_id: number; filename: string; file_type: string; file_size: number; status: string; message: string }
export interface ChunkInfo { id: number; chunk_index: number; content: string; token_count: number }

// ── Phase 1: RAG ──
export interface SearchRequest { kb_id: number; question: string; top_k?: number }
export interface SearchResult {
  chunk_id: number
  document_id: number
  content: string
  score: number
  document_title?: string
  excerpt?: string
}
export interface SearchResponse { results: SearchResult[] }
export interface AskRequest { kb_id: number; question: string; top_k?: number; conversation_id?: number | null }
export interface AskResponse { answer: string; sources: SearchResult[]; llm_error?: boolean }

// ── Phase 2: 混合检索 ──
export interface HybridSearchRequest { kb_id: number; question: string; top_k?: number; use_rerank?: boolean; history?: { role: string; content: string }[] }
export interface HybridSearchResponse { results: SearchResult[]; rewritten_query: string | null }

// ── Phase 2: 成员管理 ──
export interface MemberInfo { user_id: number; username: string; role: string; created_at: string }
export interface MemberAdd { user_id: number; role: string }
export interface MemberUpdate { role: string }

// ── Phase 2: 进度事件 ──
export interface ProgressEvent { stage: string; progress: number; message: string }
export interface ProgressDoneEvent { doc_id: number; status: string; chunk_count: number }

// ── Phase 3: 对话 ──
export interface Conversation {
  id: number
  kb_id: number
  user_id: number
  title: string | null
  message_count: number
  is_pinned: boolean
  is_starred: boolean
  created_at: string
  updated_at: string
}
export interface ConversationCreate { kb_id: number; title?: string }
export interface ConversationUpdate { title: string }
export interface ConversationListResponse {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

// ── Phase 3: 消息 ──
export interface Message {
  id: number
  conversation_id: number
  role: string
  content: string
  metadata_json?: Record<string, unknown>
  token_count: number
  tool_call_id?: string
  created_at: string
}
export interface MessageListResponse {
  items: Message[]
  has_more: boolean
}

// ── Phase 3: Agent ──
export interface ToolCallInfo {
  tool: string
  input: Record<string, unknown>
  output: string
}
export interface AgentChatRequest {
  conversation_id?: number | null
  kb_id: number
  question: string
  stream?: boolean
}
export interface AgentChatResponse {
  conversation_id: number
  answer: string
  sources: SearchResult[]
  tool_calls: ToolCallInfo[]
  token_count: number
}

// ── Phase 3: Agent SSE 事件 ──
export interface ThoughtEvent { content: string }
export interface ToolCallEvent { tool: string; input: Record<string, unknown>; tool_call_id?: string }
export interface ToolResultEvent { tool: string; output: string; chunk_count: number }
export interface SourcesEvent { sources: SearchResult[] }
export interface DoneEvent { conversation_id: number; total_tokens: number; tool_calls_count: number }

// ── Phase 4: SSE composable ──
export interface SSEEvent {
  event: string
  data: string
}
