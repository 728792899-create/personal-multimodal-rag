import { computed, ref } from 'vue'

import {
  confirmSourceDeletions,
  createSource,
  deleteSource,
  listSources,
  listSyncRuns,
  syncSource,
  type Source,
  type SourceCapabilities,
  type SourceType,
  type SyncRun,
} from '../api'


export function useSourceSync() {
  const sources = ref<Source[]>([])
  const runs = ref<SyncRun[]>([])
  const capabilities = ref<SourceCapabilities>({ types: [], directory_roots: [] })
  const loading = ref(false)
  const busySourceId = ref('')
  const error = ref('')

  const latestRuns = computed(() => {
    const result = new Map<string, SyncRun>()
    for (const run of runs.value) {
      if (!result.has(run.source_id)) result.set(run.source_id, run)
    }
    return result
  })

  async function refresh(knowledgeBaseId: string) {
    loading.value = true
    error.value = ''
    try {
      const [sourceResponse, nextRuns] = await Promise.all([
        listSources(knowledgeBaseId),
        listSyncRuns(),
      ])
      sources.value = sourceResponse.sources
      capabilities.value = sourceResponse.capabilities
      runs.value = nextRuns
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '数据源加载失败'
    } finally {
      loading.value = false
    }
  }

  async function add(
    type: SourceType,
    name: string,
    knowledgeBaseId: string,
    config: Record<string, unknown>,
  ) {
    loading.value = true
    error.value = ''
    try {
      await createSource({ type, name, knowledge_base_id: knowledgeBaseId, config })
      await refresh(knowledgeBaseId)
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '数据源创建失败'
      throw caught
    } finally {
      loading.value = false
    }
  }

  async function run(sourceId: string, knowledgeBaseId: string) {
    busySourceId.value = sourceId
    error.value = ''
    try {
      const result = await syncSource(sourceId)
      await refresh(knowledgeBaseId)
      return result
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '同步失败'
      throw caught
    } finally {
      busySourceId.value = ''
    }
  }

  async function remove(sourceId: string, knowledgeBaseId: string) {
    busySourceId.value = sourceId
    try {
      await deleteSource(sourceId)
      await refresh(knowledgeBaseId)
    } finally {
      busySourceId.value = ''
    }
  }

  async function confirm(sourceId: string, knowledgeBaseId: string) {
    busySourceId.value = sourceId
    try {
      const result = await confirmSourceDeletions(sourceId)
      await refresh(knowledgeBaseId)
      return result
    } finally {
      busySourceId.value = ''
    }
  }

  return {
    sources,
    runs,
    capabilities,
    loading,
    busySourceId,
    error,
    latestRuns,
    refresh,
    add,
    run,
    remove,
    confirm,
  }
}
