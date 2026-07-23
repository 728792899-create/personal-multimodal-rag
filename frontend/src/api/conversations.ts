import { ApiError, apiRequest, formatApiErrorDetail, getCsrfToken, jsonBody } from './client'
import type { Conversation, ConversationMessage, ConversationStreamEvent, QueryAttachmentRef, RequestOptions, RetrievalOptions } from './types'


export async function listConversations(options: RequestOptions = {}): Promise<Conversation[]> {
  const data = await apiRequest<{ conversations: Conversation[] }>('/api/conversations', {}, options)
  return data.conversations
}

export async function createConversation(title: string, knowledgeBaseIds: string[], options: RequestOptions = {}): Promise<Conversation> {
  const data = await apiRequest<{ conversation: Conversation }>('/api/conversations', { method: 'POST', ...jsonBody({ title, knowledge_base_ids: knowledgeBaseIds }) }, options)
  return data.conversation
}

export async function listConversationMessages(id: string, options: RequestOptions = {}): Promise<ConversationMessage[]> {
  const data = await apiRequest<{ messages: ConversationMessage[] }>(`/api/conversations/${encodeURIComponent(id)}/messages`, {}, options)
  return data.messages
}

export function deleteConversation(id: string, options: RequestOptions = {}) {
  return apiRequest(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }, options)
}

export async function streamConversationMessage(
  conversationId: string,
  question: string,
  retrieval: RetrievalOptions,
  onEvent: (event: ConversationStreamEvent) => void,
  options: RequestOptions = {},
  attachments: QueryAttachmentRef[] = [],
  recordAsRealUsage = false,
): Promise<void> {
  const csrfToken = getCsrfToken()
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages:stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    credentials: 'same-origin',
    body: JSON.stringify({
      question,
      ...retrieval,
      attachments,
      record_as_real_usage: recordAsRealUsage,
      ...(recordAsRealUsage ? { usage_attestation: 'human-originated' } : {}),
    }),
    signal: options.signal,
  })
  if (!response.ok || !response.body) {
    let detail = `流式请求失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) detail = formatApiErrorDetail(payload.detail, detail)
    } catch { /* response is not JSON */ }
    throw new ApiError(detail, { status: response.status, requestId: response.headers.get('x-request-id') || '' })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let lastSequence = 0
  let sawDone = false
  let streamedError: { code: string; message: string } | null = null
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const data = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!data) continue
      const event = JSON.parse(data) as ConversationStreamEvent
      if (event.sequence <= lastSequence) continue
      lastSequence = event.sequence
      onEvent(event)
      if (event.type === 'error') streamedError = { code: event.code, message: event.message }
      if (event.type === 'done') sawDone = true
    }
    if (done) break
  }
  if (streamedError) throw new ApiError(streamedError.message, { code: streamedError.code })
  if (!sawDone) throw new ApiError('流式连接在 done 事件前结束', { code: 'STREAM_INCOMPLETE' })
}
