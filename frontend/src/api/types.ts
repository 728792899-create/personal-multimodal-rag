export interface DocumentMeta {
  id: string
  filename: string
  source_type: string
  chunk_count: number
  char_count: number
  element_count?: number
  modality_counts?: Record<string, number>
  source_available?: boolean
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
  multimodal?: {
    modality_counts: Record<string, number>
    layout_bbox_coverage: number
    ocr_confidence: number | null
    caption_alignment: number
    table_structure_accuracy: number
    formula_extraction_accuracy: number
    orphan_asset_count: number
    graph_evidence_coverage: number
    index_version: string
    index_status: string
  }
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
  element_ids: string[]
  modality: DocumentElementType
  parent_element_id: string | null
  metadata: Record<string, unknown>
  score: number
  bm25_score: number
  vector_score: number
  rerank_score: number
  cross_encoder_score: number | null
  matched_terms: string[]
  snippet: string
  score_breakdown: Record<string, number | null>
  parent_context?: {
    strategy: string
    text: string
    chunk_ids: string[]
    current_chunk_id?: string
    window?: number
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

export interface DocumentElement {
  id: string
  document_id: string
  type: DocumentElementType
  order: number
  text: string
  page_number: number | null
  bbox: number[]
  heading_path: string[]
  asset_id: string | null
  caption: string
  footnotes: string[]
  table: string[][]
  latex: string
  confidence: number | null
  metadata: Record<string, unknown>
}

export interface QueryAnalysis {
  intent: string
  label: string
  matched_terms: string[]
  query_terms: string[]
  recommended: {
    search_profile: SearchProfile
    search_mode: SearchMode
    candidate_k: number
    reason: string
  }
}

export interface PipelineTrace {
  bm25?: { status: string; candidates: number; weight: number }
  vector?: { status: string; candidates: number; weight: number }
  fusion?: { candidates: number; deduped: number }
  mmr?: { selected: number; lambda: number }
  rerank?: { status: string; returned: number; provider: string }
  decision?: { status: 'refused' | 'answered'; reason: string; threshold: number; confidence: number }
  citation_audit?: { coverage: number; grounding: number; status: string }
  graph?: {
    status: 'success' | 'skipped' | string
    reason: string
    weight: number
    seed_count: number
    seed_nodes: GraphNode[]
    paths: GraphPath[]
    evidence_element_ids: string[]
    eligible: boolean
    max_hops: number
  }
}

export interface RetrievalTrace {
  query_tokens: string[]
  rewritten_queries: string[]
  total_chunks: number
  top_k: number
  candidate_k: number
  scoring: string
  bm25_weight: number
  vector_weight: number
  search_mode: SearchMode
  search_profile: SearchProfile
  strategy?: RetrievalStrategy
  graph_requested_strategy?: RetrievalStrategy
  available_chunks: number
  raw_candidates: number
  bm25_candidates?: number
  vector_candidates?: number
  deduped_candidates: number
  mmr_selected: number
  returned: number
  document_ids: string[]
  knowledge_base_ids?: string[]
  modality_filters?: DocumentElementType[]
  parent_window?: number
  embedding_provider: string
  embedding_model: string
  vector_store: string
  query_rewriter: string
  mmr_lambda: number
  reranker: string
  no_answer_threshold: number
  refuse_reason?: 'no_evidence' | 'below_threshold' | 'weak_grounding' | ''
  refusal_reason?: 'no_evidence' | 'below_threshold' | 'weak_grounding' | null
  min_score: number | null
  rewrite_status?: string
  vector_status?: string
  rerank_status?: string
  fallbacks?: Array<Record<string, string>>
  query_analysis?: QueryAnalysis
  performance?: { retrieval_ms?: number; generation_ms?: number; total_ms?: number }
  pipeline?: PipelineTrace
  query_enrichment_used?: boolean
  query_attachments?: QueryAttachmentSummary[]
}

export interface AskResponse {
  history_id?: string
  created_at?: string
  answer: string
  citations: ChunkResult[]
  retrieval_trace: RetrievalTrace
  generation_trace: {
    answer_provider?: string
    answer_model?: string
    grounded?: boolean
    skipped?: boolean
    reason?: string
    citation_count?: number
    streamed?: boolean
    incomplete?: boolean
    status?: 'failed' | 'cancelled' | string
  }
  confidence: number | null
  diagnostics?: DiagnosticItem[]
  trust?: TrustReport
  citation_audit?: CitationAudit
  gap_report?: GapReport
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
  grounding?: number
  grounded_sentence_count?: number
  grounding_overlap_threshold?: number
  weakly_grounded_claims?: Array<{
    sentence: string
    claim: string
    overlap: number
    citation_indexes: number[]
    reason: string
  }>
  checked: boolean
}

export type SearchMode = 'hybrid' | 'keyword' | 'semantic'
export type SearchProfile = 'balanced' | 'precision' | 'recall'
export type RetrievalStrategy = 'hybrid' | 'hybrid_graph' | 'auto'
export type DocumentElementType = 'text' | 'heading' | 'image' | 'table' | 'equation' | 'code' | 'mixed'
export type WorkMode = 'answer' | 'search'
export type AppMode = 'user' | 'expert'

export interface RetrievalOptions {
  top_k?: number
  candidate_k?: number
  search_mode?: SearchMode
  search_profile?: SearchProfile
  strategy?: RetrievalStrategy
  document_ids?: string[]
  knowledge_base_ids?: string[]
  bm25_weight?: number
  vector_weight?: number
  mmr_lambda?: number
  min_score?: number
  query_rewrite?: boolean
  rerank_enabled?: boolean
  graph_weight?: number
  graph_max_hops?: number
  modality_filters?: DocumentElementType[]
  parent_window?: number
}

export interface QueryAttachmentRef {
  id: string
  detail: 'low' | 'high' | 'original' | 'auto'
}

export interface QueryAsset {
  id: string
  filename: string
  media_type: string
  size_bytes: number
  width: number
  height: number
  expires_at: string
  preview_url: string
}

export interface QueryAttachmentSummary extends QueryAsset {
  detail: QueryAttachmentRef['detail']
  description: string
  keywords: string[]
  ocr_status: string
  provider: string
}

export interface GraphNode {
  node_id: string
  knowledge_base_id: string
  type: 'document' | 'element' | 'entity'
  label: string
  normalized_label: string
  document_id: string | null
  element_id: string | null
  properties: Record<string, unknown>
}

export interface GraphEdge {
  edge_id: string
  knowledge_base_id: string
  source_node_id: string
  target_node_id: string
  relation: string
  document_id: string
  evidence_element_ids: string[]
  evidence_span: string
  confidence: number
  extraction_version: string
  properties: Record<string, unknown>
}

export interface GraphPath {
  node_ids?: string[]
  edge_ids?: string[]
  labels: string[]
  relations: string[]
  evidence_element_ids: string[]
  score: number
  backend?: string
}

export interface KnowledgeGraph {
  knowledge_base_id: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  summary: {
    node_count: number
    edge_count: number
    evidence_element_count: number
    extraction_version: string
  }
}

export interface SearchResponse {
  results: ChunkResult[]
  trace: RetrievalTrace
  diagnostics?: DiagnosticItem[]
}

export interface CompareProfile {
  id: string
  label: string
  results: ChunkResult[]
  trace: RetrievalTrace
  diagnostics: DiagnosticItem[]
  summary: { returned: number; top_score: number; top_source: string; matched_terms: string[] }
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
  quality_distribution: { excellent: number; usable: number; needs_work: number }
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
  expected_document_ids?: string[]
  answerable?: boolean
  note?: string
  reviewer_id?: string
  reviewer_attestation?: string
  reviewed_at?: string
  bad_answer: string
  failure_type: string
  user_feedback: string
  citations: ChunkResult[]
  status: string
}

export interface EvalReviewPayload {
  expected_answer: string
  expected_keywords: string[]
  expected_document_ids: string[]
  answerable: boolean
  note: string
  reviewer_id: string
  reviewer_attestation: 'human-reviewed'
}

export interface EvalReviewSummary {
  total: number
  draft: number
  reviewed: number
  human_reviewed: number
  remaining_for_1_0: number
}

export interface EvaluationResult {
  question: string
  hit: boolean
  matched_keywords: string[]
  top_sources: string[]
}

export interface SystemMetrics {
  knowledge: { document_count: number; chunk_count: number; avg_quality_score: number; low_quality_count: number; modality_counts?: Record<string, number> }
  answering: {
    history_count: number
    avg_confidence: number
    fallback_count: number
    no_answer_count: number
    streamed_message_count?: number
    cancelled_count?: number
    provider_error_count?: number
    avg_first_token_ms?: number
  }
  ingestion?: {
    queue_depth: number
    failed_count: number
    cancelled_count: number
    retry_count: number
    by_status: Record<string, number>
    index_version_mismatch_count: number
    parser_fallback_count?: number
    enrichment_fallback_count?: number
  }
  graph?: { indexed_document_count: number; node_count: number; edge_count: number; retrieval_hit_count: number }
  feedback: FeedbackStats
  operations: {
    total: number
    by_type: Record<string, number>
    by_level: Record<string, number>
    recent: OperationLog[]
  }
  recommendations: string[]
}

export interface RequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

export interface AuthSession {
  required: boolean
  authenticated: boolean
  user_id: string
  workspace_id: string
  role: string
  csrf_token: string
  expires_at: string
}

export interface WorkspaceContext {
  workspace_id: string
  user_id: string
  role: 'owner' | 'member'
}

export interface StorageStatus {
  provider: string
  configured: boolean
  healthy: boolean
}

export interface QueueStatus {
  provider: string
  configured: boolean
  healthy: boolean
  depth: number
  dead_letters: number
}

export interface ReleaseGate {
  id: string
  label: string
  passed: boolean
  observed: boolean | number | string
  required: boolean | number | string
}

export interface ReleaseReadiness {
  target_version: string
  candidate_version: string
  ready: boolean
  status: 'ready' | 'blocked'
  passed_gates: number
  total_gates: number
  gates: ReleaseGate[]
  errors: string[]
  evidence_updated_at: string
  production_ready_claim: false
}

export interface RealUsageSummary {
  human_originated_questions: number
  target: 100
  remaining_for_1_0: number
  conversation_count: number
  first_recorded_at: string
  last_recorded_at: string
  attestation: 'human-originated'
}

export interface DeadLetterJob {
  id: string
  job_id: string
  error_code: string
  error_message: string
  created_at: string
}

export type SourceType = 'local_directory' | 'url_list' | 'rss_atom'

export interface Source {
  id: string
  knowledge_base_id: string
  type: SourceType
  name: string
  config: Record<string, unknown>
  enabled: boolean
  item_count: number
  deletion_candidate_count: number
  created_at: string
  updated_at: string
}

export interface SourceCapabilities {
  types: SourceType[]
  directory_roots: Array<{ id: string; label: string }>
}

export interface SourceItem {
  id: string
  source_id: string
  external_id: string
  location: string
  title: string
  content_hash: string
  status: string
  missing_successes: number
  deletion_candidate: boolean
  document_id: string
  metadata: Record<string, unknown>
  last_seen_at: string
  updated_at: string
}

export interface SyncRun {
  id: string
  source_id: string
  status: 'running' | 'succeeded' | 'partial' | 'failed'
  discovered: number
  unchanged: number
  updated: number
  deletion_candidates: number
  failed: number
  partial: boolean
  empty_result: boolean
  error_message: string
  started_at: string
  completed_at: string
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  is_default: boolean
  document_count: number
  created_at: string
  updated_at: string
}

export type IndexJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelling' | 'cancelled'

export interface IndexJob {
  id: string
  source_type: 'file' | 'url'
  source_name: string
  knowledge_base_id: string
  status: IndexJobStatus
  stage: string
  progress: number
  attempts: number
  max_attempts: number
  cancel_requested: boolean
  deduped: boolean
  error_code: string
  error_message: string
  document_id: string
  created_at: string
  updated_at: string
  started_at: string
  completed_at: string
}

export interface Conversation {
  id: string
  title: string
  knowledge_base_ids: string[]
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  status: 'streaming' | 'completed' | 'failed' | 'cancelled' | string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ProviderStatus {
  status: 'ready' | 'degraded'
  environment: string
  fallback_allowed: boolean
  runtime?: {
    deepseek?: DeepSeekRuntimeStatus
  }
  providers: {
    answer: {
      provider: string
      configured: boolean
      health?: string
      mode: string
      capabilities: string[]
      model?: string
      base_url?: string
    }
    embedding: { provider: string; configured: boolean; health?: string; mode: string; capabilities: string[] }
    enrichment?: { provider: string; configured: boolean; health?: string; mode: string; capabilities: string[] }
    vector_store: { provider: string; configured: boolean; health?: string }
    deepseek_runtime?: DeepSeekRuntimeStatus
  }
}

export interface DeepSeekRuntimeStatus {
  provider?: string
  connected?: boolean
  configured?: boolean
  active?: boolean
  status?: string
  health?: string
  mode?: string
  capabilities?: string[]
  temporary?: boolean
  base_url?: string
  model?: string
  runtime_override?: boolean
  credential_state?: string
}

export interface DeepSeekRuntimeMutation {
  status?: string
  runtime?: {
    deepseek?: DeepSeekRuntimeStatus
  }
  connection?: DeepSeekRuntimeStatus
}

export interface IngestionRequestOptions extends RequestOptions {
  parserProfile?: 'builtin' | 'auto' | 'mineru' | 'docling' | 'paddleocr'
  enrichModalities?: boolean
  buildGraph?: boolean
}

export type ConversationStreamEvent =
  | { type: 'query.enrichment.started'; request_id: string; conversation_id: string; message_id: string; sequence: number; attachment_count: number }
  | { type: 'query.enrichment.completed'; request_id: string; conversation_id: string; message_id: string; sequence: number; attachments: QueryAttachmentSummary[]; provider: string }
  | { type: 'retrieval.started'; request_id: string; conversation_id: string; message_id: string; sequence: number; context_message_count: number }
  | ({ type: 'retrieval.completed'; request_id: string; conversation_id: string; message_id: string; sequence: number } & Partial<AskResponse>)
  | { type: 'answer.delta'; request_id: string; conversation_id: string; message_id: string; sequence: number; delta: string }
  | { type: 'answer.completed' | 'refusal'; request_id: string; conversation_id: string; message_id: string; sequence: number; response: AskResponse }
  | { type: 'error'; request_id: string; conversation_id: string; message_id: string; sequence: number; code: string; message: string }
  | { type: 'done'; request_id: string; conversation_id: string; message_id: string; sequence: number; status: string; real_usage_recorded?: boolean }
