import { apiRequest, jsonBody } from './client'
import type {
  RequestOptions,
  Source,
  SourceCapabilities,
  SourceItem,
  SourceType,
  SyncRun,
} from './types'


export async function listSources(
  knowledgeBaseId = '',
  options: RequestOptions = {},
): Promise<{ sources: Source[]; capabilities: SourceCapabilities }> {
  const query = knowledgeBaseId ? `?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}` : ''
  return apiRequest(`/api/sources${query}`, {}, options)
}

export async function createSource(
  payload: {
    type: SourceType
    name: string
    knowledge_base_id: string
    config: Record<string, unknown>
    enabled?: boolean
  },
  options: RequestOptions = {},
): Promise<Source> {
  const response = await apiRequest<{ source: Source }>(
    '/api/sources',
    { method: 'POST', ...jsonBody(payload) },
    options,
  )
  return response.source
}

export async function getSource(
  sourceId: string,
  options: RequestOptions = {},
): Promise<{ source: Source; items: SourceItem[] }> {
  return apiRequest(`/api/sources/${encodeURIComponent(sourceId)}`, {}, options)
}

export async function deleteSource(sourceId: string, options: RequestOptions = {}): Promise<void> {
  await apiRequest(
    `/api/sources/${encodeURIComponent(sourceId)}`,
    { method: 'DELETE' },
    options,
  )
}

export async function syncSource(sourceId: string, options: RequestOptions = {}): Promise<SyncRun> {
  const response = await apiRequest<{ sync_run: SyncRun }>(
    `/api/sources/${encodeURIComponent(sourceId)}/sync`,
    { method: 'POST' },
    { ...options, timeoutMs: options.timeoutMs ?? 120_000 },
  )
  return response.sync_run
}

export async function listSyncRuns(
  sourceId = '',
  options: RequestOptions = {},
): Promise<SyncRun[]> {
  const query = sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : ''
  const response = await apiRequest<{ sync_runs: SyncRun[] }>(
    `/api/sync-runs${query}`,
    {},
    options,
  )
  return response.sync_runs
}

export async function confirmSourceDeletions(
  sourceId: string,
  itemIds: string[] = [],
  options: RequestOptions = {},
): Promise<{ removed_items: number; removed_documents: number }> {
  return apiRequest(
    `/api/sources/${encodeURIComponent(sourceId)}/deletions:confirm`,
    { method: 'POST', ...jsonBody({ item_ids: itemIds }) },
    options,
  )
}

export const exportConversationUrl = (id: string) =>
  `/api/exports/conversations/${encodeURIComponent(id)}.md`
export const exportHistoryUrl = (id: string) =>
  `/api/exports/history/${encodeURIComponent(id)}.md`
export const exportKnowledgeCardUrl = (id: string) =>
  `/api/exports/knowledge-cards/${encodeURIComponent(id)}.md`
