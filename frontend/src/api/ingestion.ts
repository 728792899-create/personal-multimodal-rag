import { apiRequest, jsonBody } from './client'
import type { IndexJob, RequestOptions } from './types'


export async function enqueueFileIngestion(file: File, knowledgeBaseId: string, options: RequestOptions = {}): Promise<IndexJob> {
  const form = new FormData()
  form.append('file', file)
  form.append('knowledge_base_id', knowledgeBaseId)
  const data = await apiRequest<{ job: IndexJob }>('/api/ingestions/file', { method: 'POST', body: form }, { timeoutMs: 90_000, ...options })
  return data.job
}

export async function enqueueUrlIngestion(url: string, knowledgeBaseId: string, title = '', options: RequestOptions = {}): Promise<IndexJob> {
  const data = await apiRequest<{ job: IndexJob }>('/api/ingestions/url', { method: 'POST', ...jsonBody({ url, title, knowledge_base_id: knowledgeBaseId }) }, options)
  return data.job
}

export async function listIndexJobs(limit = 50, options: RequestOptions = {}): Promise<IndexJob[]> {
  const data = await apiRequest<{ jobs: IndexJob[] }>(`/api/index-jobs?limit=${limit}`, {}, options)
  return data.jobs
}

export async function getIndexJob(id: string, options: RequestOptions = {}): Promise<IndexJob> {
  const data = await apiRequest<{ job: IndexJob }>(`/api/index-jobs/${encodeURIComponent(id)}`, {}, options)
  return data.job
}

export async function retryIndexJob(id: string, options: RequestOptions = {}): Promise<IndexJob> {
  const data = await apiRequest<{ job: IndexJob }>(`/api/index-jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }, options)
  return data.job
}

export async function cancelIndexJob(id: string, options: RequestOptions = {}): Promise<IndexJob> {
  const data = await apiRequest<{ job: IndexJob }>(`/api/index-jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }, options)
  return data.job
}
