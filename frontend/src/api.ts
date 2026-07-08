export interface DocumentMeta {
  id: string
  filename: string
  source_type: string
  chunk_count: number
  char_count: number
  metadata: Record<string, unknown>
  quality?: DocumentQuality
  summary?: DocumentSummary
  lifecycle?: LifecycleEvent[]
}

export interface DocumentQuality {
  score: number
  level: 'excellent' | 'usable' | 'needs_review' | 'poor'
  char_count: number
  page_count: number
  chunk_count: number
  avg_chunk_length: number
  min_chunk_length: number
  max_chunk_length: number
  weird_char_ratio: number
  duplicate_chunk_ratio: number
  signals: Array<{ level: 'info' | 'warning' | 'error'; message: string; delta: number }>
  suggestions: string[]
  updated_at: string
}

export interface DocumentSummary {
  one_sentence: string
  key_points: string[]
  key_concepts: string[]
  suggested_questions: string[]
  updated_at: string
}

export interface LifecycleEvent {
  stage: string
  status: string
  started_at: string
  ended_at: string
  duration_ms: number
  error: string
  retry_count: number
}

export interface ChunkResult {
  id: string
  document_id: string
  filename: string
  index: number
  text: string
  page_number: number | null
  heading_path: string[]
  metadata: Record<string, unknown>
  score: number
  bm25_score: number
  vector_score: number
  rerank_score: number
  cross_encoder_score: number | null
  matched_terms: string[]
  snippet: string
  score_breakdown: Record<string, number>
  parent_context?: {
    strategy: string
    text: string
    chunk_ids: string[]
    current_chunk_id?: string
  }
}

export interface DiagnosticItem {
  level: 'info' | 'warning' | 'error'
  title: string
  message: string
  action: string
  actions?: DiagnosticAction[]
}

export interface DiagnosticAction {
  id: string
  label: string
  type: 'retry_search' | 'index' | 'ui'
  payload: Record<string, unknown>
}

export interface DocumentPage {
  page_number: number | null
  text: string
  metadata: Record<string, unknown>
}

export interface DocumentDetail {
  document: DocumentMeta & {
    title: string | null
    created_at: string
    page_count: number
    pages: DocumentPage[]
  }
  chunks: Array<Omit<ChunkResult, 'score' | 'bm25_score' | 'vector_score' | 'rerank_score'>>
}

export interface AskResponse {
  history_id?: string
  created_at?: string
  answer: string
  citations: ChunkResult[]
  retrieval_trace: {
    query_tokens: string[]
    rewritten_queries: string[]
    total_chunks: number
    top_k: number
    candidate_k: number
    scoring: string
    bm25_weight: number
    vector_weight: number
    search_mode: 'hybrid' | 'keyword' | 'semantic'
    search_profile: 'balanced' | 'precision' | 'recall'
    available_chunks: number
    raw_candidates: number
    deduped_candidates: number
    mmr_selected: number
    returned: number
    document_ids: string[]
    embedding_provider: string
    embedding_model: string
    vector_store: string
    query_rewriter: string
    mmr_lambda: number
    reranker: string
    no_answer_threshold: number
    min_score: number | null
    rewrite_status?: string
    vector_status?: string
    rerank_status?: string
    fallbacks?: Array<Record<string, string>>
    query_analysis?: QueryAnalysis
  }
  generation_trace: {
    answer_provider?: string
    answer_model?: string
    grounded?: boolean
    skipped?: boolean
    reason?: string
    citation_count?: number
  }
  confidence: number | null
  diagnostics?: DiagnosticItem[]
  trust?: TrustReport
  citation_audit?: CitationAudit
  gap_report?: GapReport
}

export interface QueryAnalysis {
  intent: string
  label: string
  matched_terms: string[]
  query_terms: string[]
  recommended: {
    search_profile: 'balanced' | 'precision' | 'recall'
    search_mode: 'hybrid' | 'keyword' | 'semantic'
    candidate_k: number
    reason: string
  }
}

export interface GapReport {
  query_intent: QueryAnalysis
  missing_topics: Array<{
    topic: string
    matched_query_terms: string[]
    reason: string
    suggestion: string
  }>
  failure_types: Record<string, number>
  needs_action: boolean
  suggestions: string[]
  created_at: string
}

export interface TrustReport {
  level: 'strong' | 'medium' | 'weak' | 'unknown' | string
  label: string
  reason: string
  evidence_count: number
  source_count: number
  top_score: number
  confidence: number
  coverage: number
  recommendations: string[]
}

export interface CitationAudit {
  coverage: number
  sentence_count: number
  supported_sentence_count: number
  unsupported_sentence_count: number
  unsupported_claims: string[]
  checked: boolean
}

export interface RetrievalOptions {
  top_k?: number
  candidate_k?: number
  search_mode?: 'hybrid' | 'keyword' | 'semantic'
  search_profile?: 'balanced' | 'precision' | 'recall'
  document_ids?: string[]
  bm25_weight?: number
  vector_weight?: number
  mmr_lambda?: number
  min_score?: number
  query_rewrite?: boolean
  rerank_enabled?: boolean
}

export interface SearchResponse {
  results: ChunkResult[]
  trace: AskResponse['retrieval_trace']
  diagnostics?: DiagnosticItem[]
}

export interface CompareProfile {
  id: string
  label: string
  results: ChunkResult[]
  trace: AskResponse['retrieval_trace']
  diagnostics: DiagnosticItem[]
  summary: {
    returned: number
    top_score: number
    top_source: string
    matched_terms: string[]
  }
}

export interface SearchCompareResponse {
  query: string
  profiles: CompareProfile[]
  best_profile: string | null
}

export interface HistoryItem extends AskResponse {
  id: string
  question: string
  created_at: string
}

export interface KnowledgeOverview {
  document_count: number
  chunk_count: number
  char_count: number
  avg_quality_score: number
  quality_distribution: {
    excellent: number
    usable: number
    needs_work: number
  }
  themes: string[]
  recent_questions: string[]
  low_quality_documents: Array<{ id: string; filename: string; score: number }>
  suggestions: string[]
  updated_at: string
}

export interface FeedbackStats {
  total: number
  positive: number
  negative: number
  failure_types: Record<string, number>
  recent: Array<Record<string, unknown>>
}

export interface FeedbackPayload {
  history_id?: string
  question: string
  answer?: string
  rating: 'up' | 'down'
  feedback_text?: string
  failure_type?: 'no_evidence' | 'low_confidence' | 'wrong_citation' | 'unsupported_claim' | 'bad_answer' | 'retrieval_miss' | 'other'
  expected_answer?: string
  citations?: ChunkResult[]
}

export interface FeedbackResponse {
  feedback: Record<string, unknown>
  eval_case: Record<string, unknown> | null
  stats: FeedbackStats
}

export interface OperationLog {
  id: string
  event_type: string
  level: 'info' | 'warning' | 'error' | string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export interface ChunkContext {
  found: boolean
  chunk_id: string
  document_id: string
  filename: string
  page_number: number | null
  heading_path: string[]
  context: Array<{
    id: string
    index: number
    text: string
    page_number: number | null
    heading_path: string[]
    is_current: boolean
  }>
}

export type RewriteStyle = 'short' | 'detailed' | 'briefing' | 'highlights' | 'study' | 'faq'

export interface RewriteResponse {
  style: RewriteStyle
  label: string
  instruction: string
  rewritten: string
  created_at: string
}

export interface KnowledgeCard {
  id: string
  title: string
  question: string
  answer: string
  citations: ChunkResult[]
  tags: string[]
  source_documents: string[]
  created_at: string
}

export interface EvalDraft {
  id?: string
  question: string
  expected_answer: string
  expected_keywords: string[]
  bad_answer: string
  failure_type: string
  user_feedback: string
  citations: ChunkResult[]
  status: string
}

export interface EvaluationResult {
  question: string
  hit: boolean
  matched_keywords: string[]
  top_sources: string[]
}

export interface SystemMetrics {
  knowledge: {
    document_count: number
    chunk_count: number
    avg_quality_score: number
    low_quality_count: number
  }
  answering: {
    history_count: number
    avg_confidence: number
    fallback_count: number
    no_answer_count: number
  }
  feedback: FeedbackStats
  operations: {
    total: number
    by_type: Record<string, number>
    by_level: Record<string, number>
    recent: OperationLog[]
  }
  recommendations: string[]
}

export async function uploadDocument(file: File) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/documents', {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '上传失败' }))
    throw new Error(error.detail || '上传失败')
  }
  return response.json()
}

export async function importUrl(url: string, title = '') {
  const response = await fetch('/api/imports/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, title }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'URL 导入失败' }))
    throw new Error(error.detail || 'URL 导入失败')
  }
  return response.json()
}

export async function listDocuments(): Promise<DocumentMeta[]> {
  const response = await fetch('/api/documents')
  const data = await response.json()
  return data.documents
}

export async function getKnowledgeOverview(): Promise<KnowledgeOverview> {
  const response = await fetch('/api/knowledge/overview')
  if (!response.ok) {
    throw new Error('获取知识库概览失败')
  }
  return response.json()
}

export async function getDocumentDetail(documentId: string): Promise<DocumentDetail> {
  const response = await fetch(`/api/documents/${documentId}`)
  if (!response.ok) {
    throw new Error('获取文档详情失败')
  }
  return response.json()
}

export async function deleteDocument(documentId: string) {
  const response = await fetch(`/api/documents/${documentId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('删除文档失败')
  }
  return response.json()
}

export async function rebuildDocument(documentId: string) {
  const response = await fetch(`/api/documents/${documentId}/rebuild`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('重建索引失败')
  }
  return response.json()
}

export async function rebuildAllDocuments() {
  const response = await fetch('/api/documents/rebuild-all', {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('重建全部索引失败')
  }
  return response.json()
}

export async function askQuestion(question: string, options: RetrievalOptions = {}): Promise<AskResponse> {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, ...options }),
  })
  if (!response.ok) {
    throw new Error('问答请求失败')
  }
  return response.json()
}

export async function searchDocuments(query: string, options: RetrievalOptions = {}): Promise<SearchResponse> {
  const response = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...options }),
  })
  if (!response.ok) {
    throw new Error('检索请求失败')
  }
  return response.json()
}

export async function compareSearchStrategies(query: string, options: RetrievalOptions = {}): Promise<SearchCompareResponse> {
  const response = await fetch('/api/search/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...options }),
  })
  if (!response.ok) {
    throw new Error('检索策略对比失败')
  }
  return response.json()
}

export async function listHistory(limit = 30): Promise<HistoryItem[]> {
  const response = await fetch(`/api/history?limit=${limit}`)
  if (!response.ok) {
    throw new Error('获取问答历史失败')
  }
  const data = await response.json()
  return data.history
}

export async function clearHistory() {
  const response = await fetch('/api/history', {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('清空问答历史失败')
  }
  return response.json()
}

export async function submitFeedback(payload: FeedbackPayload): Promise<FeedbackResponse> {
  const response = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('提交反馈失败')
  }
  return response.json()
}

export async function listOperations(limit = 20): Promise<OperationLog[]> {
  const response = await fetch(`/api/operations?limit=${limit}`)
  if (!response.ok) {
    throw new Error('获取操作日志失败')
  }
  const data = await response.json()
  return data.operations
}

export async function getChunkContext(chunkId: string, window = 1): Promise<ChunkContext> {
  const response = await fetch(`/api/chunks/${encodeURIComponent(chunkId)}/context?window=${window}`)
  if (!response.ok) {
    throw new Error('获取引用上下文失败')
  }
  return response.json()
}

export async function rewriteAnswer(
  question: string,
  answer: string,
  style: RewriteStyle,
  citations: ChunkResult[] = [],
): Promise<RewriteResponse> {
  const response = await fetch('/api/answer/rewrite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, answer, style, citations }),
  })
  if (!response.ok) {
    throw new Error('答案改写失败')
  }
  return response.json()
}

export async function saveKnowledgeCard(question: string, answer: string, citations: ChunkResult[], tags: string[] = []): Promise<KnowledgeCard> {
  const response = await fetch('/api/knowledge/cards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, answer, citations, tags }),
  })
  if (!response.ok) {
    throw new Error('保存知识卡片失败')
  }
  const data = await response.json()
  return data.card
}

export async function listKnowledgeCards(limit = 30): Promise<KnowledgeCard[]> {
  const response = await fetch(`/api/knowledge/cards?limit=${limit}`)
  if (!response.ok) {
    throw new Error('获取知识卡片失败')
  }
  const data = await response.json()
  return data.cards
}

export async function listEvalDrafts(limit = 30): Promise<EvalDraft[]> {
  const response = await fetch(`/api/eval/drafts?limit=${limit}`)
  if (!response.ok) {
    throw new Error('获取评测草稿失败')
  }
  const data = await response.json()
  return data.drafts
}

export async function createEvalCase(question: string, expectedKeywords: string[] = [], expectedAnswer = '', note = ''): Promise<EvalDraft> {
  const response = await fetch('/api/eval/cases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      expected_keywords: expectedKeywords,
      expected_answer: expectedAnswer,
      note,
    }),
  })
  if (!response.ok) {
    throw new Error('创建评测 case 失败')
  }
  const data = await response.json()
  return data.case
}

export async function runEvalDrafts(limit = 30): Promise<{ case_count: number; results: EvaluationResult[] }> {
  const response = await fetch(`/api/eval/run-drafts?limit=${limit}`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('运行评测草稿失败')
  }
  return response.json()
}

export async function getSystemMetrics(): Promise<SystemMetrics> {
  const response = await fetch('/api/metrics')
  if (!response.ok) {
    throw new Error('获取系统指标失败')
  }
  return response.json()
}
