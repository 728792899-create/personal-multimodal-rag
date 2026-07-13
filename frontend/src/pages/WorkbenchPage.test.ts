import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkbenchPage from './WorkbenchPage.vue'
import { answerFixture, metricsFixture, overviewFixture } from '../test/fixtures'


function json(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } }))
}

describe('WorkbenchPage workflows', () => {
  let documents: Array<Record<string, unknown>>
  let calls: Array<{ path: string; init: RequestInit }>
  let askResponse = answerFixture()

  beforeEach(() => {
    documents = []
    calls = []
    askResponse = answerFixture()
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init: RequestInit = {}) => {
      const path = String(input)
      calls.push({ path, init })
      if (path === '/api/documents' && init.method === 'POST') {
        documents = [{ id: 'doc-1', filename: 'rag.md', source_type: 'markdown', chunk_count: 1, char_count: 30, metadata: { index_status: 'indexed' }, quality: { score: 90 } }]
        return json({ document: documents[0], chunks: [] })
      }
      if (path === '/api/imports/url') return json({ document: { id: 'url-1' }, chunks: [] })
      if (path === '/api/documents') return json({ documents })
      if (path === '/api/knowledge/overview') return json({ ...overviewFixture, document_count: documents.length })
      if (path.startsWith('/api/history')) return json({ history: [] })
      if (path.startsWith('/api/operations')) return json({ operations: [] })
      if (path.startsWith('/api/knowledge/cards')) return json({ cards: [] })
      if (path.startsWith('/api/eval/drafts')) return json({ drafts: [] })
      if (path === '/api/metrics') return json(metricsFixture)
      if (path === '/api/ask') return json(askResponse)
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

    expect(calls.some((call) => call.path === '/api/documents' && call.init.method === 'POST' && call.init.body instanceof FormData)).toBe(true)
    expect(wrapper.text()).toContain('rag.md')

    await wrapper.get('[data-testid="url-input"]').setValue('https://example.com/guide')
    expect(wrapper.get('[data-testid="url-import-button"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form.url-form').trigger('submit')
    await flushPromises()
    expect(calls.map((call) => ({ path: call.path, method: call.init.method }))).toContainEqual({ path: '/api/imports/url', method: 'POST' })
  })

  it('submits expert parameters, opens citation context, and turns feedback into an eval draft', async () => {
    const wrapper = mount(WorkbenchPage)
    await flushPromises()

    await wrapper.get('[data-testid="mode-expert"]').trigger('click')
    await wrapper.get('input[name="candidate-k"]').setValue('40')
    await wrapper.get('textarea[name="question"]').setValue('RAG 如何评测？')
    await wrapper.get('[data-testid="run-query"]').trigger('click')
    await flushPromises()

    const askCall = calls.find((call) => call.path === '/api/ask')!
    expect(JSON.parse(String(askCall.init.body))).toMatchObject({ question: 'RAG 如何评测？', candidate_k: 40 })
    expect(wrapper.text()).toContain('固定黄金集评测')

    await wrapper.get('[data-testid="citation-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('上下文证据')

    await wrapper.get('[data-testid="feedback-down"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已生成评测草稿')
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
})
