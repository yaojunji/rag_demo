// ---------- 仪表盘 / 反馈 / 检索调试 ----------
export interface DashboardPoint {
  date: string
  count: number
}

export interface FeedbackStats {
  up: number
  down: number
  total: number
  up_rate: number
  by_kb: { kb_id: number | null; kb_name: string; count: number }[]
  by_user: { user_id: number; username: string; count: number }[]
}

export interface DashboardOut {
  totals: SystemStats
  chat_trend: DashboardPoint[]
  doc_trend: DashboardPoint[]
  kb_stats: { kb_id: number; kb_name: string; docs: number; chunks: number }[]
  feedback: FeedbackStats
  top_questions: { question: string; count: number }[]
}

export interface DebugHit {
  chunk_id: number
  doc_id: number | null
  doc_name: string
  kb_id: number | null
  score: number
  text: string
}

export interface RagDebugOut {
  query: string
  embed_model: string
  timings_ms: Record<string, number>
  vector_hits: DebugHit[]
  keyword_hits: DebugHit[]
  fused_hits: DebugHit[]
  reranked_hits: DebugHit[]
  final_hits: DebugHit[]
}// ---------- 涓庡悗绔?schemas 瀵归綈鐨勭被鍨?----------
export interface User {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'editor' | 'viewer'
  tenant_id: number | null
  is_active: boolean
  created_at: string
}

export interface TokenResp {
  access_token: string
  token_type: string
  user: User
}

export interface KnowledgeBase {
  id: number
  name: string
  description: string
  tenant_id: number | null
  embed_model: string
  chunk_size: number
  chunk_overlap: number
  doc_count: number
  chunk_count: number
  welcome_questions: string[]
  created_at: string
  updated_at: string
}

export interface DocumentItem {
  id: number
  kb_id: number
  filename: string
  file_type: string
  file_size: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  progress: number
  error: string
  chunk_count: number
  created_by: number
  created_at: string
  updated_at: string
}

export interface ChunkItem {
  doc_id: number
  chunk_index: number
  content: string
  metadata: { page?: number | null; section?: string | null }
}

export interface Citation {
  doc_id: number
  doc_name: string
  chunk_index: number
  score: number
  snippet: string
  page?: number | null
  kb_id?: number | null
  ref_index?: number
}

export interface ChatMessageItem {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  citations: Citation[] | null
  model: string
  latency_ms: number
  created_at: string
}

export interface ChatSessionItem {
  id: number
  title: string
  kb_id: number | null
  created_at: string
  updated_at: string
}

export interface AuditItem {
  id: number
  user_id: number | null
  username: string
  tenant_id: number | null
  action: string
  resource_type: string
  resource_id: string
  detail: string
  ip: string
  created_at: string
}

export interface SystemStats {
  tenants: number
  users: number
  knowledge_bases: number
  documents: number
  chunks: number
  chat_messages: number
  audit_logs: number
  llm_model: string
  embed_model: string
  gateway: string
  vector_store: string
  version: string
}

export interface RAGConfig {
  llm_models: string[]
  embed_models: string[]
  gateway: string
  chunk_size: number
  chunk_overlap: number
  retrieve_top_k: number
  rerank_top_k: number
  enable_rerank: boolean
  enable_hybrid: boolean
  max_upload_mb: number
  default_llm_model: string
  default_embed_model: string
}

export interface Tenant {
  id: number
  name: string
  description: string
  created_at: string
}

export interface Page<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

// ---------- SSE 浜嬩欢 ----------
export interface SSEEvent {
  type: string
  content?: string
  citations?: Citation[]
  model?: string
  session_id?: number
  message_id?: number
  timings_ms?: Record<string, number>
  message?: string
  questions?: string[]
  suggested?: string[]
}

// ---------- 鍓嶇娑堟伅妯″瀷 ----------
export interface Msg {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[] | null
  model?: string
  streaming?: boolean
  error?: boolean
  feedback?: 'up' | 'down' | null
  suggestions?: string[]
}