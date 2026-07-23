import { apiRequest, jsonBody } from './client'
import type { DocumentDetail, DocumentElement, DocumentMeta, KnowledgeOverview, RequestOptions } from './types'


export function uploadDocument(file: File, options: RequestOptions = {}) {
  const form = new FormData()
  form.append('file', file)
  return apiRequest('/api/documents', { method: 'POST', body: form }, { timeoutMs: 90_000, ...options })
}

export function importUrl(url: string, title = '', options: RequestOptions = {}) {
  return apiRequest('/api/imports/url', { method: 'POST', ...jsonBody({ url, title }) }, { timeoutMs: 30_000, ...options })
}

export async function listDocuments(options: RequestOptions = {}, knowledgeBaseId = ''): Promise<DocumentMeta[]> {
  const query = knowledgeBaseId ? `?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}` : ''
  const data = await apiRequest<{ documents: DocumentMeta[] }>(`/api/documents${query}`, {}, options)
  return data.documents
}

export function getKnowledgeOverview(options: RequestOptions = {}): Promise<KnowledgeOverview> {
  return apiRequest('/api/knowledge/overview', {}, options)
}

export function getDocumentDetail(documentId: string, options: RequestOptions = {}): Promise<DocumentDetail> {
  return apiRequest(`/api/documents/${encodeURIComponent(documentId)}`, {}, options)
}

export async function getDocumentElements(documentId: string, options: RequestOptions = {}): Promise<DocumentElement[]> {
  const data = await apiRequest<{ elements: DocumentElement[] }>(`/api/documents/${encodeURIComponent(documentId)}/elements`, {}, options)
  return data.elements
}

export function deleteDocument(documentId: string, options: RequestOptions = {}) {
  return apiRequest(`/api/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' }, options)
}

export function rebuildDocument(documentId: string, options: RequestOptions = {}) {
  return apiRequest(`/api/documents/${encodeURIComponent(documentId)}/rebuild`, { method: 'POST' }, { timeoutMs: 90_000, ...options })
}

export function rebuildAllDocuments(options: RequestOptions = {}) {
  return apiRequest('/api/documents/rebuild-all', { method: 'POST' }, { timeoutMs: 120_000, ...options })
}
