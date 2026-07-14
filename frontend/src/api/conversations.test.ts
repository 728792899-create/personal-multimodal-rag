import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamConversationMessage } from './conversations'


function streamResponse(frames: Array<Record<string, unknown>>) {
  const text = frames.map((frame) => `event: ${frame.type}\r\ndata: ${JSON.stringify(frame)}\r\n\r\n`).join('')
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

describe('streamConversationMessage', () => {
  afterEach(() => vi.unstubAllGlobals())

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
      message: 'provider unavailable',
    })
  })
})
