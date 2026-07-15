import { ref } from 'vue'

import { getDocumentDetail, getDocumentElements, type DocumentDetail, type DocumentElement } from '../api'


export function useDocumentViewer() {
  const document = ref<DocumentDetail | null>(null)
  const elements = ref<DocumentElement[]>([])
  const loading = ref(false)
  const focusedElementId = ref('')

  async function open(documentId: string, elementId = '') {
    loading.value = true
    try {
      const [detail, nextElements] = await Promise.all([
        getDocumentDetail(documentId),
        getDocumentElements(documentId),
      ])
      document.value = detail
      elements.value = nextElements
      focusedElementId.value = elementId
    } finally {
      loading.value = false
    }
  }

  function clear() {
    document.value = null
    elements.value = []
    focusedElementId.value = ''
  }

  return { document, elements, loading, focusedElementId, open, clear }
}
