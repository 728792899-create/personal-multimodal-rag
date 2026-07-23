import { apiRequest, jsonBody } from './client'
import type {
  ChunkResult,
  EvalDraft,
  EvalReviewPayload,
  EvalReviewSummary,
  EvaluationResult,
  FeedbackPayload,
  FeedbackResponse,
  KnowledgeCard,
  OperationLog,
  RequestOptions,
  RewriteResponse,
  RewriteStyle,
  SystemMetrics,
} from './types'


export function submitFeedback(payload: FeedbackPayload, options: RequestOptions = {}): Promise<FeedbackResponse> {
  return apiRequest('/api/feedback', { method: 'POST', ...jsonBody(payload) }, options)
}

export async function listOperations(limit = 20, options: RequestOptions = {}): Promise<OperationLog[]> {
  const data = await apiRequest<{ operations: OperationLog[] }>(`/api/operations?limit=${limit}`, {}, options)
  return data.operations
}

export function rewriteAnswer(question: string, answer: string, style: RewriteStyle, citations: ChunkResult[] = [], options: RequestOptions = {}): Promise<RewriteResponse> {
  return apiRequest('/api/answer/rewrite', { method: 'POST', ...jsonBody({ question, answer, style, citations }) }, options)
}

export async function saveKnowledgeCard(question: string, answer: string, citations: ChunkResult[], tags: string[] = [], options: RequestOptions = {}): Promise<KnowledgeCard> {
  const data = await apiRequest<{ card: KnowledgeCard }>('/api/knowledge/cards', { method: 'POST', ...jsonBody({ question, answer, citations, tags }) }, options)
  return data.card
}

export async function listKnowledgeCards(limit = 30, options: RequestOptions = {}): Promise<KnowledgeCard[]> {
  const data = await apiRequest<{ cards: KnowledgeCard[] }>(`/api/knowledge/cards?limit=${limit}`, {}, options)
  return data.cards
}

export async function listEvalDrafts(limit = 30, options: RequestOptions = {}): Promise<EvalDraft[]> {
  const data = await apiRequest<{ drafts: EvalDraft[] }>(`/api/eval/drafts?limit=${limit}`, {}, options)
  return data.drafts
}

export async function createEvalCase(question: string, expectedKeywords: string[] = [], expectedAnswer = '', note = '', options: RequestOptions = {}): Promise<EvalDraft> {
  const data = await apiRequest<{ case: EvalDraft }>('/api/eval/cases', {
    method: 'POST',
    ...jsonBody({ question, expected_keywords: expectedKeywords, expected_answer: expectedAnswer, note }),
  }, options)
  return data.case
}

export async function reviewEvalCase(caseId: string, payload: EvalReviewPayload, options: RequestOptions = {}): Promise<{ case: EvalDraft; summary: EvalReviewSummary }> {
  return apiRequest(`/api/eval/cases/${encodeURIComponent(caseId)}`, {
    method: 'PATCH',
    ...jsonBody(payload),
  }, options)
}

export function getEvalReviewSummary(options: RequestOptions = {}): Promise<EvalReviewSummary> {
  return apiRequest('/api/eval/review-summary', {}, options)
}

export function runEvalDrafts(limit = 30, options: RequestOptions = {}): Promise<{ case_count: number; results: EvaluationResult[] }> {
  return apiRequest(`/api/eval/run-drafts?limit=${limit}`, { method: 'POST' }, { timeoutMs: 60_000, ...options })
}

export function getSystemMetrics(options: RequestOptions = {}): Promise<SystemMetrics> {
  return apiRequest('/api/metrics', {}, options)
}
