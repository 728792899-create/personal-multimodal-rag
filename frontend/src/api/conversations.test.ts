import { afterEach, describe, expect, it, vi } from 'vitest'

import { setCsrfToken } from './client'
import { streamConversationMessage } from './conversations'


function streamResponse(frames: Array<Record<string, unknown>>) {
  const text = frames.map((frame) => `event: ${frame.type}\r\ndata: ${JSON.stringify(frame)}\r\n\r\n`).join('')
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

describe('streamConversationMessage', () => {
  afterEach(() => {
    setCsrfToken('')
    vi.unstubAllGlobals()
  })

  it('parses typed SSE frames in order and forwards final audit', async () => {
    const events = [
      { type: 'retrieval.started', sequence: 1, request_id: 'r', conversation_id: 'c', message_id: 'm', context_message_count: 0 },
      { type: 'answer.delta', sequence: 2, request_id: 'r', conversation_id: 'c', message_id: 'm', delta: 'grounded' },
      { type: 'answer.delta', sequence: 2, request_id: 'r', conversation_id: 'c', message_id: 'm', delta: 'duplicate' },
      { type: 'answer.completed', sequence: 3, request_id: 'r', conversation_id: 'c', message_id: 'm', response: { answer: 'grounded', citations: [], retrieval_trace: {}, generation_trace: {}, confidence: 1 } },
      { type: 'done', sequence: 4, request_id: 'r', conversation_id: 'c', message_id: 'm', status: 'completed' },
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(events)))
    const received: string[] = []

    await streamConversationMessage('c', 'question', {}, (event) => received.push(event.type))

    expect(received).toEqual(['retrieval.started', 'answer.delta', 'answer.completed', 'done'])
  })

  it('turns a streamed error frame into a typed failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      { type: 'error', sequence: 1, request_id: 'r', conversation_id: 'c', message_id: 'm', code: 'STREAM_FAILED', message: 'provider unavailable' },
    ])))

    await expect(streamConversationMessage('c', 'question', {}, () => undefined)).rejects.toMatchObject({
      code: 'STREAM_FAILED',
      message: '服务暂时不可用，请稍后重试。',
    })
  })

  it('does not misreport an answer-provider stream failure as a browser network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      { type: 'retrieval.completed', sequence: 1, request_id: 'r', conversation_id: 'c', message_id: 'm', citations: [{ id: 'chunk-1' }] },
      { type: 'error', sequence: 2, request_id: 'r', conversation_id: 'c', message_id: 'm', code: 'STREAM_FAILED', message: 'connection reset by peer' },
      { type: 'done', sequence: 3, request_id: 'r', conversation_id: 'c', message_id: 'm', status: 'failed' },
    ])))

    await expect(streamConversationMessage('c', 'question', {}, () => undefined)).rejects.toMatchObject({
      code: 'STREAM_FAILED',
      message: '回答生成失败，已保留检索证据，请重试。',
      requestId: 'r',
    })
  })

  it('classifies a gateway timeout as an answer-service timeout', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 504 })))

    await expect(streamConversationMessage('c', 'question', {}, () => undefined)).rejects.toMatchObject({
      status: 504,
      code: 'ANSWER_SERVICE_TIMEOUT',
      message: '回答服务超时，未完成生成；请重试。',
    })
  })

  it('bounds a stalled stream and distinguishes it from user cancellation', async () => {
    vi.stubGlobal('fetch', vi.fn((_input: string | URL | Request, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    })))

    await expect(streamConversationMessage('c', 'question', {}, () => undefined, { timeoutMs: 10 })).rejects.toMatchObject({
      code: 'STREAM_TIMEOUT',
      message: '回答等待超时，请重试；已完成的检索证据不会丢失。',
    })
  })

  it('preserves caller cancellation even when the signal was already aborted', async () => {
    vi.stubGlobal('fetch', vi.fn((_input: string | URL | Request, init?: RequestInit) => (
      init?.signal?.aborted
        ? Promise.reject(new DOMException('aborted', 'AbortError'))
        : new Promise(() => undefined)
    )))
    const controller = new AbortController()
    controller.abort()

    await expect(streamConversationMessage(
      'c',
      'question',
      {},
      () => undefined,
      { signal: controller.signal, timeoutMs: 10 },
    )).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('carries CSRF and only sends the human attestation after explicit opt-in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse([
      { type: 'done', sequence: 1, request_id: 'r', conversation_id: 'c', message_id: 'm', status: 'completed', real_usage_recorded: true },
    ]))
    vi.stubGlobal('fetch', fetchMock)
    setCsrfToken('csrf-test')

    await streamConversationMessage('c', 'a real question', {}, () => undefined, {}, [], true)

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test')
    expect(JSON.parse(String(init.body))).toMatchObject({
      record_as_real_usage: true,
      usage_attestation: 'human-originated',
    })
  })
})
