import { computed, ref } from 'vue'

import { createKnowledgeBase, deleteKnowledgeBase, listKnowledgeBases, updateKnowledgeBase, type KnowledgeBase } from '../api'


export function useKnowledgeBases() {
  const knowledgeBases = ref<KnowledgeBase[]>([])
  const selectedKnowledgeBaseId = ref('default')
  const loadingKnowledgeBases = ref(false)
  const newKnowledgeBaseName = ref('')

  const selectedKnowledgeBase = computed(() =>
    knowledgeBases.value.find((item) => item.id === selectedKnowledgeBaseId.value) ?? knowledgeBases.value[0] ?? null,
  )

  async function refreshKnowledgeBases() {
    loadingKnowledgeBases.value = true
    try {
      knowledgeBases.value = await listKnowledgeBases()
      if (!knowledgeBases.value.some((item) => item.id === selectedKnowledgeBaseId.value)) {
        selectedKnowledgeBaseId.value = knowledgeBases.value.find((item) => item.is_default)?.id ?? knowledgeBases.value[0]?.id ?? 'default'
      }
    } finally {
      loadingKnowledgeBases.value = false
    }
  }

  async function addKnowledgeBase() {
    const name = newKnowledgeBaseName.value.trim()
    if (!name) return null
    const created = await createKnowledgeBase(name)
    newKnowledgeBaseName.value = ''
    await refreshKnowledgeBases()
    selectedKnowledgeBaseId.value = created.id
    return created
  }

  async function renameKnowledgeBase(id: string, name: string) {
    await updateKnowledgeBase(id, name)
    await refreshKnowledgeBases()
  }

  async function removeKnowledgeBase(id: string, force = false) {
    await deleteKnowledgeBase(id, force)
    await refreshKnowledgeBases()
  }

  return {
    knowledgeBases,
    selectedKnowledgeBaseId,
    selectedKnowledgeBase,
    loadingKnowledgeBases,
    newKnowledgeBaseName,
    refreshKnowledgeBases,
    addKnowledgeBase,
    renameKnowledgeBase,
    removeKnowledgeBase,
  }
}
