import { computed, type Ref } from 'vue'

import type { AskResponse } from '../api'


export function useQualityAudit(answer: Ref<AskResponse | null>) {
  const isRefusal = computed(() => Boolean(answer.value?.retrieval_trace.refusal_reason))
  const diagnostics = computed(() => answer.value?.diagnostics ?? [])
  const citationAudit = computed(() => answer.value?.citation_audit)
  const trust = computed(() => answer.value?.trust)
  const queryAttachmentAudit = computed(() => answer.value?.retrieval_trace.query_attachments ?? [])

  return { isRefusal, diagnostics, citationAudit, trust, queryAttachmentAudit }
}
