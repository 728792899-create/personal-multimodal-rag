import { apiRequest } from './client'
import type { QueryAsset, RequestOptions } from './types'


export async function uploadQueryAssets(
  files: File[],
  knowledgeBaseId: string,
  options: RequestOptions = {},
): Promise<QueryAsset[]> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('knowledge_base_id', knowledgeBaseId)
  const data = await apiRequest<{ assets: QueryAsset[] }>(
    '/api/query-assets',
    { method: 'POST', body: form },
    { timeoutMs: 60_000, ...options },
  )
  return data.assets
}

export function deleteQueryAsset(id: string, options: RequestOptions = {}) {
  return apiRequest(`/api/query-assets/${encodeURIComponent(id)}`, { method: 'DELETE' }, options)
}
