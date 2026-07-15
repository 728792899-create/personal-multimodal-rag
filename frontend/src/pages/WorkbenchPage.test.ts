import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkbenchPage from './WorkbenchPage.vue'
import { answerFixture, metricsFixture, overviewFixture } from '../test/fixtures'


function json(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } }))
}

function sse(events: Array<{ type: string; data: Record<string, unknown> }>) {
  const body = events.map(({ type, data }, index) => {
    const payload = { type, request_id: 'req-stream', conversation_id: 'conv-1', message_id: 'msg-1', sequence: index + 1, ...data }
    return `event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`
  }).join('')
  return Promise.resolve(new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }))
}

describe('WorkbenchPage workflows', () => {
  let documents: Array<Record<string, unknown>>
  let calls: Array<{ path: string; init: RequestInit }>
  let askResponse = answerFixture()
  let conversations: Array<Record<string, unknown>>
  let knowledgeBases: Array<Record<string, unknown>>

  beforeEach(() => {
    documents = []
    calls = []
    askResponse = answerFixture()
    conversations = []
    knowledgeBases = [{ id: 'default', name: '默认知识库', description: '', is_default: true, document_count: 0, created_at: '', updated_at: '' }]
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init: RequestInit = {}) => {
      const path = String(input)
      calls.push({ path, init })
      if (path === '/api/knowledge-bases' && init.method === 'POST') {
        const created = { id: 'kb-2', name: JSON.parse(String(init.body)).name, description: '', is_default: false, document_count: 0, created_at: '', updated_at: '' }
        knowledgeBases.push(created)
        return json({ knowledge_base: created }, 201)
      }
      if (path === '/api/knowledge-bases') return json({ knowledge_bases: knowledgeBases.map((item) => ({ ...item, document_count: item.id === 'default' ? documents.length : 0 })) })
      if (path === '/api/query-assets' && init.method === 'POST') return json({ assets: [{ id: 'query-1', filename: 'diagram.png', media_type: 'image/png', size_bytes: 120, width: 32, height: 24, expires_at: '2099-01-01T00:00:00', preview_url: '/api/assets/query-1' }] }, 201)
      if (path === '/api/query-assets/query-1' && init.method === 'DELETE') return json({ deleted: true })
      if (path === '/api/ingestions/file' && init.method === 'POST') {
        documents = [{ id: 'doc-1', filename: 'rag.md', source_type: 'markdown', chunk_count: 1, char_count: 30, metadata: { index_status: 'indexed' }, quality: { score: 90 } }]
        return json({ job: { id: 'job-file', source_type: 'file', source_name: 'rag.md', knowledge_base_id: 'default', status: 'succeeded', stage: 'complete', progress: 100, attempts: 1, max_attempts: 3, cancel_requested: false, deduped: false, error_code: '', error_message: '', document_id: 'doc-1', created_at: '', updated_at: '', started_at: '', completed_at: '' } }, 202)
      }
      if (path === '/api/ingestions/url') return json({ job: { id: 'job-url', source_type: 'url', source_name: 'example.com', knowledge_base_id: 'default', status: 'succeeded', stage: 'complete', progress: 100, attempts: 1, max_attempts: 3, cancel_requested: false, deduped: false, error_code: '', error_message: '', document_id: 'url-1', created_at: '', updated_at: '', started_at: '', completed_at: '' } }, 202)
      if (path.startsWith('/api/index-jobs?')) return json({ jobs: [] })
      if (path.startsWith('/api/documents')) return json({ documents })
      if (path === '/api/knowledge/overview') return json({ ...overviewFixture, document_count: documents.length })
      if (path.startsWith('/api/history')) return json({ history: [] })
      if (path.startsWith('/api/operations')) return json({ operations: [] })
      if (path.startsWith('/api/knowledge/cards')) return json({ cards: [] })
      if (path.startsWith('/api/eval/drafts')) return json({ drafts: [] })
      if (path === '/api/metrics') return json(metricsFixture)
      if (path === '/api/providers/status') return json({ status: 'ready', environment: 'test', fallback_allowed: true, providers: { answer: { provider: 'template', configured: true, mode: 'offline', capabilities: ['answer'] }, embedding: { provider: 'mock', configured: true, mode: 'offline', capabilities: ['embeddings'] }, vector_store: { provider: 'memory', configured: true } } })
      if (path === '/api/conversations' && init.method === 'POST') {
        const conversation = { id: 'conv-1', title: '新会话', knowledge_base_ids: ['default'], message_count: 0, created_at: '', updated_at: '' }
        conversations = [conversation]
        return json({ conversation }, 201)
      }
      if (path === '/api/conversations') return json({ conversations })
      if (path === '/api/conversations/conv-1/messages') return json({ messages: [{ id: 'msg-1', conversation_id: 'conv-1', role: 'assistant', content: askResponse.answer, status: 'completed', metadata: { response: askResponse }, created_at: '', updated_at: '' }] })
      if (path === '/api/conversations/conv-1/messages:stream') {
        const base = [
          { type: 'retrieval.started', data: { context_message_count: 0 } },
          { type: 'retrieval.completed', data: { citations: askResponse.citations, retrieval_trace: askResponse.retrieval_trace, confidence: askResponse.confidence, diagnostics: askResponse.diagnostics } },
        ]
        return askResponse.retrieval_trace.refusal_reason
          ? sse([...base, { type: 'refusal', data: { response: askResponse } }, { type: 'done', data: { status: 'completed' } }])
          : sse([...base, { type: 'answer.delta', data: { delta: askResponse.answer } }, { type: 'answer.completed', data: { response: askResponse } }, { type: 'done', data: { status: 'completed' } }])
      }
      if (path.startsWith('/api/chunks/')) return json({ found: true, chunk_id: 'doc-1:0', document_id: 'doc-1', filename: 'rag.md', page_number: 1, heading_path: [], context: [{ id: 'doc-1:0', index: 0, text: '上下文证据', page_number: 1, heading_path: [], is_current: true }] })
      if (path === '/api/feedback') return json({ feedback: {}, eval_case: { status: 'draft' }, stats: { total: 1, positive: 0, negative: 1, failure_types: { bad_answer: 1 }, recent: [] } })
      return json({ detail: `unhandled ${path}` }, 404)
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uploads a file and imports a URL with visible progress and refresh', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    const file = new File(['# RAG'], 'rag.md', { type: 'text/markdown' })
    const fileInput = wrapper.get('[data-testid="file-input"]').element as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { configurable: true, value: [file] })
    await wrapper.get('[data-testid="file-input"]').trigger('change')
    await wrapper.get('[data-testid="upload-button"]').trigger('click')
    await flushPromises()

    expect(calls.some((call) => call.path === '/api/ingestions/file' && call.init.method === 'POST' && call.init.body instanceof FormData)).toBe(true)
    expect(wrapper.text()).toContain('rag.md')

    await wrapper.get('[data-testid="url-input"]').setValue('https://example.com/guide')
    expect(wrapper.get('[data-testid="url-import-button"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form.url-form').trigger('submit')
    await flushPromises()
    expect(calls.map((call) => ({ path: call.path, method: call.init.method }))).toContainEqual({ path: '/api/ingestions/url', method: 'POST' })
  })

  it('submits expert parameters, opens citation context, and turns feedback into an eval draft', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    await wrapper.get('[data-testid="mode-expert"]').trigger('click')
    await wrapper.get('input[name="candidate-k"]').setValue('40')
    await wrapper.get('textarea[name="question"]').setValue('RAG 如何评测？')
    await wrapper.get('[data-testid="run-query"]').trigger('click')
    await flushPromises()

    const askCall = calls.find((call) => call.path.endsWith('/messages:stream'))!
    expect(JSON.parse(String(askCall.init.body))).toMatchObject({ question: 'RAG 如何评测？', candidate_k: 40 })
    expect(wrapper.text()).toContain('固定黄金集评测')

    await wrapper.get('[data-testid="citation-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('上下文证据')

    await wrapper.get('[data-testid="feedback-down"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已生成评测草稿')
  })

  it('uploads a temporary query image and sends typed attachment options', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    const file = new File(['image'], 'diagram.png', { type: 'image/png' })
    const input = wrapper.get('[data-testid="query-image-input"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await wrapper.get('[data-testid="query-image-input"]').trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('diagram.png')
    await wrapper.get('.attachment-detail select').setValue('high')
    await wrapper.get('textarea[name="question"]').setValue('图中是什么？')
    await wrapper.get('[data-testid="run-query"]').trigger('click')
    await flushPromises()

    const askCall = calls.find((call) => call.path.endsWith('/messages:stream'))!
    expect(JSON.parse(String(askCall.init.body))).toMatchObject({
      strategy: 'auto',
      attachments: [{ id: 'query-1', detail: 'high' }],
    })
  })

  it('disables execution and explains invalid expert parameters', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    await wrapper.get('[data-testid="mode-expert"]').trigger('click')
    await wrapper.get('input[name="candidate-k"]').setValue('')

    expect(wrapper.get('[data-testid="run-query"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="status"]').text()).toContain('候选池需为 1–80 的整数')
    expect(calls.some((call) => call.path.endsWith('/messages:stream'))).toBe(false)
  })

  it('renders no-evidence refusal as a successful guarded outcome', async () => {
    askResponse = answerFixture({
      answer: '根据当前知识库资料，无法确定。',
      citations: [],
      confidence: 0,
      retrieval_trace: {
        ...answerFixture().retrieval_trace,
        refusal_reason: 'no_evidence',
        pipeline: { ...answerFixture().retrieval_trace.pipeline, decision: { status: 'refused', reason: 'no_evidence', threshold: 0.05, confidence: 0 } },
      },
    })
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    await wrapper.get('textarea[name="question"]').setValue('有没有 Kubernetes？')
    await wrapper.get('[data-testid="run-query"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="status"]').text()).toContain('已安全拒答')
    expect(wrapper.text()).toContain('无法确定')
    expect(wrapper.text()).toContain('没有可引用证据')
  })

  it('creates and switches knowledge bases while exposing provider health', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    expect(wrapper.text()).toContain('Provider ready')
    await wrapper.get('.inline-create input').setValue('研究资料')
    await wrapper.get('form.inline-create').trigger('submit')
    await flushPromises()

    expect(calls.some((call) => call.path === '/api/knowledge-bases' && call.init.method === 'POST')).toBe(true)
    expect((wrapper.get('#knowledge-base-select').element as HTMLSelectElement).value).toBe('kb-2')
    expect(wrapper.text()).toContain('研究资料')
  })
})
