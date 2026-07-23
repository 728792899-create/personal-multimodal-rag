import { apiRequest, jsonBody } from './client'
import type {
  AskResponse,
  ChunkContext,
  HistoryItem,
  RequestOptions,
  RetrievalOptions,
  SearchCompareResponse,
  SearchResponse,
} from './types'


export function askQuestion(question: string, options: RetrievalOptions = {}, request: RequestOptions = {}): Promise<AskResponse> {
  return apiRequest('/api/ask', { method: 'POST', ...jsonBody({ question, ...options }) }, { timeoutMs: 60_000, ...request })
}

export function searchDocuments(query: string, options: RetrievalOptions = {}, request: RequestOptions = {}): Promise<SearchResponse> {
  return apiRequest('/api/search', { method: 'POST', ...jsonBody({ query, ...options }) }, request)
}

export function compareSearchStrategies(query: string, options: RetrievalOptions = {}, request: RequestOptions = {}): Promise<SearchCompareResponse> {
  return apiRequest('/api/search/compare', { method: 'POST', ...jsonBody({ query, ...options }) }, { timeoutMs: 60_000, ...request })
}

export async function listHistory(limit = 30, options: RequestOptions = {}): Promise<HistoryItem[]> {
  const data = await apiRequest<{ history: HistoryItem[] }>(`/api/history?limit=${limit}`, {}, options)
  return data.history
}

export function clearHistory(options: RequestOptions = {}) {
  return apiRequest('/api/history', { method: 'DELETE' }, options)
}

export function getChunkContext(chunkId: string, windowSize = 1, options: RequestOptions = {}): Promise<ChunkContext> {
  return apiRequest(`/api/chunks/${encodeURIComponent(chunkId)}/context?window=${windowSize}`, {}, options)
}
