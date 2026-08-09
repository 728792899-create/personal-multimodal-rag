import { computed, ref } from 'vue'

import { deleteQueryAsset, uploadQueryAssets, type QueryAsset, type QueryAttachmentRef } from '../api'
import { localizedSystemText } from '../localization'


export function useMultimodalQuery() {
  const attachments = ref<QueryAsset[]>([])
  const detail = ref<QueryAttachmentRef['detail']>('auto')
  const uploading = ref(false)
  const error = ref('')
  let controller: AbortController | null = null

  const attachmentRefs = computed<QueryAttachmentRef[]>(() => attachments.value.map((asset) => ({
    id: asset.id,
    detail: detail.value,
  })))

  async function addFiles(files: File[], knowledgeBaseId: string) {
    const available = 4 - attachments.value.length
    if (!files.length || available <= 0) return
    const selected = files.slice(0, available)
    error.value = files.length > available ? `每次提问最多保留 4 张图片，已选择前 ${available} 张。` : ''
    controller?.abort()
    controller = new AbortController()
    uploading.value = true
    try {
      const created = await uploadQueryAssets(selected, knowledgeBaseId, { signal: controller.signal })
      attachments.value.push(...created)
    } catch (caught) {
      error.value = localizedSystemText(caught instanceof Error ? caught.message : '', '图片上传失败')
    } finally {
      uploading.value = false
      controller = null
    }
  }

  async function remove(id: string) {
    const existing = attachments.value.find((item) => item.id === id)
    attachments.value = attachments.value.filter((item) => item.id !== id)
    if (!existing) return
    try {
      await deleteQueryAsset(id)
    } catch {
      // Expired or already deleted assets need no further UI recovery.
    }
  }

  async function clear() {
    const ids = attachments.value.map((item) => item.id)
    attachments.value = []
    await Promise.allSettled(ids.map((id) => deleteQueryAsset(id)))
  }

  function cancel() {
    controller?.abort()
  }

  return { attachments, attachmentRefs, detail, uploading, error, addFiles, remove, clear, cancel }
}
