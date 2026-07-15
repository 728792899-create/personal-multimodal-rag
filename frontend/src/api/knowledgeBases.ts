import { apiRequest, jsonBody } from './client'
import type { KnowledgeBase, KnowledgeGraph, RequestOptions } from './types'


export async function listKnowledgeBases(options: RequestOptions = {}): Promise<KnowledgeBase[]> {
  const data = await apiRequest<{ knowledge_bases: KnowledgeBase[] }>('/api/knowledge-bases', {}, options)
  return data.knowledge_bases
}

export async function createKnowledgeBase(name: string, description = '', options: RequestOptions = {}): Promise<KnowledgeBase> {
  const data = await apiRequest<{ knowledge_base: KnowledgeBase }>('/api/knowledge-bases', { method: 'POST', ...jsonBody({ name, description }) }, options)
  return data.knowledge_base
}

export async function updateKnowledgeBase(id: string, name: string, description?: string, options: RequestOptions = {}): Promise<KnowledgeBase> {
  const data = await apiRequest<{ knowledge_base: KnowledgeBase }>(`/api/knowledge-bases/${encodeURIComponent(id)}`, { method: 'PATCH', ...jsonBody({ name, description }) }, options)
  return data.knowledge_base
}

export function deleteKnowledgeBase(id: string, force = false, options: RequestOptions = {}) {
  return apiRequest(`/api/knowledge-bases/${encodeURIComponent(id)}?force=${force}`, { method: 'DELETE' }, options)
}

export function getKnowledgeBaseGraph(id: string, limit = 500, options: RequestOptions = {}): Promise<KnowledgeGraph> {
  return apiRequest(`/api/knowledge-bases/${encodeURIComponent(id)}/graph?limit=${Math.max(1, Math.min(limit, 2000))}`, {}, options)
}
