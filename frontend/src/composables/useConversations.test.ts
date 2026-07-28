import { afterEach, describe, expect, it, vi } from 'vitest'

import { answerFixture } from '../test/fixtures'
import { useConversations } from './useConversations'


function json(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  }))
}

function successfulAnswerStream() {
  const response = answerFixture()
  const events = [
    { type: 'retrieval.started', context_message_count: 0 },
    {
      type: 'retrieval.completed',
      citations: response.citations,
      retrieval_trace: response.retrieval_trace,
      confidence: response.confidence,
      diagnostics: response.diagnostics,
    },
    { type: 'answer.delta', delta: response.answer },
    { type: 'answer.completed', response },
    { type: 'done', status: 'completed' },
  ]
  const body = events.map((event, index) => (
    `event: ${event.type}\ndata: ${JSON.stringify({
      request_id: 'request-1',
      conversation_id: 'conversation-1',
      message_id: 'assistant-1',
      sequence: index + 1,
      ...event,
    })}\n\n`
  )).join('')
  return Promise.resolve(new Response(body, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  }))
}

describe('持久化会话流', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it.each([
    ['空消息列表', []],
    ['只读到用户消息', [{
      id: 'user-1',
      conversation_id: 'conversation-1',
      role: 'user',
      content: 'RAG 如何评测？',
      status: 'completed',
      metadata: {},
      created_at: '',
      updated_at: '',
    }]],
  ])('最终事件完成后不会被暂时滞后的%s降级', async (_label, delayedMessages) => {
    const conversation = {
      id: 'conversation-1',
      title: '新会话',
      knowledge_base_ids: ['default'],
      message_count: delayedMessages.length,
      created_at: '',
      updated_at: '',
    }
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init: RequestInit = {}) => {
      const path = String(input)
      if (path === '/api/conversations' && init.method === 'POST') {
        return json({ conversation }, 201)
      }
      if (path === '/api/conversations') {
        return json({ conversations: [conversation] })
      }
      if (path === '/api/conversations/conversation-1/messages') {
        return json({ messages: delayedMessages })
      }
      if (path === '/api/conversations/conversation-1/messages:stream') {
        return successfulAnswerStream()
      }
      return json({ detail: `未处理的测试路由：${path}` }, 404)
    }))
    const state = useConversations()

    const response = await state.askInConversation(
      'RAG 如何评测？',
      ['default'],
      {},
      [],
      false,
      vi.fn(),
    )

    expect(response.answer).toContain('固定黄金集')
    expect(state.streamPhase.value).toBe('completed')
    expect(state.activeConversationId.value).toBe('conversation-1')
  })
})
