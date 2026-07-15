import type { AskResponse, RetrievalTrace } from '../api'


export const traceFixture: RetrievalTrace = {
  query_tokens: ['rag'],
  rewritten_queries: ['RAG 如何评测？'],
  total_chunks: 20,
  available_chunks: 20,
  top_k: 5,
  candidate_k: 12,
  raw_candidates: 12,
  bm25_candidates: 9,
  vector_candidates: 11,
  deduped_candidates: 10,
  mmr_selected: 6,
  returned: 2,
  scoring: '0.62 * normalized BM25 + 0.38 * vector similarity',
  bm25_weight: 0.62,
  vector_weight: 0.38,
  search_mode: 'hybrid',
  search_profile: 'balanced',
  document_ids: [],
  embedding_provider: 'mock',
  embedding_model: 'hash-mock',
  vector_store: 'memory',
  query_rewriter: 'off',
  mmr_lambda: 0.78,
  reranker: 'keyword',
  no_answer_threshold: 0.05,
  min_score: 0.05,
  rewrite_status: 'disabled',
  vector_status: 'success',
  rerank_status: 'success',
  fallbacks: [],
  pipeline: {
    bm25: { status: 'success', candidates: 9, weight: 0.62 },
    vector: { status: 'success', candidates: 11, weight: 0.38 },
    fusion: { candidates: 12, deduped: 10 },
    mmr: { selected: 6, lambda: 0.78 },
    rerank: { status: 'success', returned: 2, provider: 'keyword' },
    decision: { status: 'answered', reason: 'evidence_accepted', threshold: 0.05, confidence: 0.82 },
    citation_audit: { coverage: 1, grounding: 0.8, status: 'checked' },
  },
}

export function answerFixture(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    history_id: 'history-1',
    answer: 'RAG 使用固定黄金集评测召回和引用质量。[1]',
    citations: [{
      id: 'doc-1:0',
      document_id: 'doc-1',
      filename: 'rag.md',
      index: 0,
      text: '固定黄金集覆盖 Recall@K、MRR 与引用准确率。',
      page_number: 1,
      heading_path: ['评测'],
      element_ids: ['doc-1:element:0'],
      modality: 'text',
      parent_element_id: 'doc-1:element:0',
      metadata: {},
      score: 0.8,
      bm25_score: 1.2,
      vector_score: 0.7,
      rerank_score: 0.82,
      cross_encoder_score: null,
      matched_terms: ['评测'],
      snippet: '固定黄金集覆盖 Recall@K、MRR 与引用准确率。',
      score_breakdown: { bm25_weighted: 0.5, vector_weighted: 0.3 },
    }],
    retrieval_trace: traceFixture,
    generation_trace: { answer_provider: 'template', answer_model: '-', grounded: true },
    confidence: 0.82,
    trust: {
      level: 'strong', label: '证据充分', reason: '引用覆盖充分。', evidence_count: 1,
      source_count: 1, top_score: 0.82, confidence: 0.82, coverage: 1, recommendations: [],
    },
    citation_audit: {
      coverage: 1, sentence_count: 1, supported_sentence_count: 1,
      unsupported_sentence_count: 0, unsupported_claims: [], grounding: 0.8,
      grounded_sentence_count: 1, checked: true,
    },
    diagnostics: [],
    ...overrides,
  }
}

export const overviewFixture = {
  document_count: 0,
  chunk_count: 0,
  char_count: 0,
  avg_quality_score: 0,
  quality_distribution: { excellent: 0, usable: 0, needs_work: 0 },
  themes: [], recent_questions: [], low_quality_documents: [],
  suggestions: ['上传第一份资料开始。'], updated_at: '2026-07-14T00:00:00Z',
}

export const metricsFixture = {
  knowledge: { document_count: 0, chunk_count: 0, avg_quality_score: 0, low_quality_count: 0 },
  answering: { history_count: 0, avg_confidence: 0, fallback_count: 0, no_answer_count: 0 },
  feedback: { total: 0, positive: 0, negative: 0, failure_types: {}, recent: [] },
  operations: { total: 0, by_type: {}, by_level: {}, recent: [] },
  recommendations: [],
}
