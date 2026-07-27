import { ref } from 'vue'

import { getKnowledgeBaseGraph, type KnowledgeGraph } from '../api'
import { localizedSystemText } from '../localization'


export function useGraphTrace() {
  const graph = ref<KnowledgeGraph | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(knowledgeBaseId: string) {
    loading.value = true
    error.value = ''
    try {
      graph.value = await getKnowledgeBaseGraph(knowledgeBaseId)
    } catch (caught) {
      graph.value = null
      error.value = localizedSystemText(caught instanceof Error ? caught.message : '', '图谱加载失败')
    } finally {
      loading.value = false
    }
  }

  return { graph, loading, error, load }
}
