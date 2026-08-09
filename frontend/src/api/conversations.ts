import { ApiError, apiRequest, formatApiErrorDetail, getCsrfToken, jsonBody } from './client'
import type { Conversation, ConversationMessage, ConversationStreamEvent, QueryAttachmentRef, RequestOptions, RetrievalOptions } from './types'
import { localizedSystemText } from '../localization'

const DEFAULT_STREAM_IDLE_TIMEOUT_MS = 90_000

function answerServiceHttpError(status: number) {
  if (status === 504) {
    return {
      code: 'ANSWER_SERVICE_TIMEOUT',
      message: '回答服务超时，未完成生成；请重试。',
    }
  }
  if ([502, 503].includes(status)) {
    return {
      code: 'ANSWER_SERVICE_UNAVAILABLE',
      message: '回答服务暂时不可用，未完成生成；请稍后重试。',
    }
  }
  return null
}

function streamedFailureMessage(code: string, message: string) {
  const lowered = message.trim().toLowerCase()
  if (lowered.includes('timeout') || lowered.includes('timed out')) {
    return '回答服务超时，已保留检索证据，请重试。'
  }
  if (lowered.includes('provider') || lowered.includes('unavailable')) {
    return '服务暂时不可用，请稍后重试。'
  }
  if (code === 'STREAM_FAILED') {
    return '回答生成失败，已保留检索证据，请重试。'
  }
  return localizedSystemText(message, '回答生成失败，已保留检索证据，请重试。')
}

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
  const controller = new AbortController()
  let timedOut = false
  let timeoutId = 0
  let observedRequestId = ''
  const timeoutMs = options.timeoutMs ?? DEFAULT_STREAM_IDLE_TIMEOUT_MS
  const abortForTimeout = () => {
    timedOut = true
    controller.abort()
  }
  const resetIdleTimeout = () => {
    window.clearTimeout(timeoutId)
    timeoutId = window.setTimeout(abortForTimeout, Math.max(1, timeoutMs))
  }
  const handleCallerAbort = () => controller.abort()
  options.signal?.addEventListener('abort', handleCallerAbort, { once: true })
  if (options.signal?.aborted) controller.abort()
  resetIdleTimeout()

  const csrfToken = getCsrfToken()
  try {
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
      signal: controller.signal,
    })
    resetIdleTimeout()
    if (!response.ok || !response.body) {
      const serviceError = answerServiceHttpError(response.status)
      if (serviceError) {
        throw new ApiError(serviceError.message, {
          status: response.status,
          code: serviceError.code,
          requestId: response.headers.get('x-request-id') || '',
        })
      }
      let detail = `流式请求失败（${response.status}）`
      try {
        const payload = await response.json()
        if (payload?.detail) detail = formatApiErrorDetail(payload.detail, detail)
      } catch { /* response is not JSON */ }
      throw new ApiError(detail, {
        status: response.status,
        code: response.status === 429 ? 'RATE_LIMITED' : 'HTTP_ERROR',
        requestId: response.headers.get('x-request-id') || '',
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let lastSequence = 0
    let sawDone = false
    let sawFinalResponse = false
    let sawRetrieval = false
    let streamedErrorCode = ''
    let streamedErrorText = ''
    const processFrame = (frame: string) => {
      const data = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!data) return
      let event: ConversationStreamEvent
      try {
        event = JSON.parse(data) as ConversationStreamEvent
      } catch {
        throw new ApiError('回答流格式异常，请重试。', { code: 'STREAM_PROTOCOL_ERROR' })
      }
      if (event.sequence <= lastSequence) return
      lastSequence = event.sequence
      observedRequestId = event.request_id
      onEvent(event)
      if (event.type === 'retrieval.completed') sawRetrieval = true
      if (event.type === 'answer.completed' || event.type === 'refusal') sawFinalResponse = true
      if (event.type === 'error') {
        streamedErrorCode = event.code
        streamedErrorText = event.message
      }
      if (event.type === 'done') sawDone = true
    }
    while (true) {
      const { value, done } = await reader.read()
      resetIdleTimeout()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) processFrame(frame)
      if (done) break
    }
    if (buffer.trim()) processFrame(buffer)
    if (streamedErrorCode) {
      throw new ApiError(streamedFailureMessage(streamedErrorCode, streamedErrorText), {
        code: streamedErrorCode,
        requestId: observedRequestId,
      })
    }
    // A fully audited final event is usable even if an intermediary closes before
    // forwarding the trailing bookkeeping frame.
    if (!sawDone && !sawFinalResponse) {
      throw new ApiError(
        sawRetrieval
          ? '回答连接意外中断，已保留检索证据，请重试。'
          : '回答连接意外中断，请重试。',
        { code: 'STREAM_INCOMPLETE', requestId: observedRequestId },
      )
    }
  } catch (error) {
    if (timedOut) {
      throw new ApiError('回答等待超时，请重试；已完成的检索证据不会丢失。', {
        status: 408,
        code: 'STREAM_TIMEOUT',
        requestId: observedRequestId,
      })
    }
    if (options.signal?.aborted) throw new DOMException('Request cancelled', 'AbortError')
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('回答连接意外中断，请重试；已完成的检索证据不会丢失。', {
      code: 'STREAM_CONNECTION_FAILED',
      requestId: observedRequestId,
    })
  } finally {
    window.clearTimeout(timeoutId)
    options.signal?.removeEventListener('abort', handleCallerAbort)
  }
}
