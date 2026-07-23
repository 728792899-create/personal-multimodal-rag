import { computed, ref } from 'vue'

import {
  cancelIndexJob,
  enqueueFileIngestion,
  enqueueUrlIngestion,
  getIndexJob,
  listIndexJobs,
  retryIndexJob,
  type IndexJob,
} from '../api'


const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

export function useIngestionJobs() {
  const indexJobs = ref<IndexJob[]>([])
  const activeUploadJobId = ref('')
  const activeUrlJobId = ref('')

  const activeJobs = computed(() => indexJobs.value.filter((job) => !TERMINAL.has(job.status)))

  function mergeJob(job: IndexJob) {
    const index = indexJobs.value.findIndex((item) => item.id === job.id)
    if (index >= 0) indexJobs.value.splice(index, 1, job)
    else indexJobs.value.unshift(job)
  }

  async function refreshIndexJobs() {
    indexJobs.value = await listIndexJobs(30)
  }

  async function waitForJob(job: IndexJob, signal?: AbortSignal): Promise<IndexJob> {
    let current = job
    mergeJob(current)
    for (let attempt = 0; attempt < 900 && !TERMINAL.has(current.status); attempt += 1) {
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          window.clearTimeout(timeout)
          reject(new DOMException('Request cancelled', 'AbortError'))
        }
        const timeout = window.setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, 100)
        if (signal?.aborted) onAbort()
        else signal?.addEventListener('abort', onAbort, { once: true })
      })
      current = await getIndexJob(current.id, { signal })
      mergeJob(current)
    }
    if (!TERMINAL.has(current.status)) throw new Error('索引任务等待超时，请在任务中心继续查看。')
    if (current.status === 'failed') throw new Error(current.error_message || '索引任务失败')
    if (current.status === 'cancelled') throw new DOMException('Request cancelled', 'AbortError')
    return current
  }

  async function ingestFile(file: File, knowledgeBaseId: string, signal?: AbortSignal) {
    const job = await enqueueFileIngestion(file, knowledgeBaseId, { signal })
    activeUploadJobId.value = job.id
    try {
      return await waitForJob(job, signal)
    } finally {
      activeUploadJobId.value = ''
    }
  }

  async function ingestUrl(url: string, knowledgeBaseId: string, signal?: AbortSignal) {
    const job = await enqueueUrlIngestion(url, knowledgeBaseId, '', { signal })
    activeUrlJobId.value = job.id
    try {
      return await waitForJob(job, signal)
    } finally {
      activeUrlJobId.value = ''
    }
  }

  async function cancelJob(id: string) {
    mergeJob(await cancelIndexJob(id))
  }

  async function retryJob(id: string) {
    const job = await retryIndexJob(id)
    mergeJob(job)
    return waitForJob(job)
  }

  return {
    indexJobs,
    activeJobs,
    activeUploadJobId,
    activeUrlJobId,
    refreshIndexJobs,
    ingestFile,
    ingestUrl,
    cancelJob,
    retryJob,
  }
}
