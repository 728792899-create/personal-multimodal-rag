import { expect, test, type Page } from '@playwright/test'

import { answerFixture, metricsFixture, overviewFixture } from '../src/test/fixtures'


async function installOfflineApi(page: Page) {
  const documents: Array<Record<string, unknown>> = []
  const askBodies: Array<Record<string, unknown>> = []
  let evalDrafts: Array<Record<string, unknown>> = []

  await page.route('http://127.0.0.1:4173/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const json = async (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (path === '/api/documents' && method === 'POST') {
      const doc = {
        id: 'doc-upload', filename: 'quality-guide.md', source_type: 'markdown', chunk_count: 2,
        char_count: 180, metadata: { index_status: 'indexed' }, quality: { score: 92 },
      }
      documents.push(doc)
      return json({ document: doc, chunks: [] })
    }
    if (path === '/api/imports/url' && method === 'POST') {
      const doc = {
        id: 'doc-url', filename: 'example.com-guide.html', source_type: 'url', chunk_count: 1,
        char_count: 80, metadata: { index_status: 'indexed' }, quality: { score: 84 },
      }
      documents.push(doc)
      return json({ document: doc, chunks: [] })
    }
    if (path === '/api/documents') return json({ documents })
    if (path === '/api/knowledge/overview') return json({
      ...overviewFixture,
      document_count: documents.length,
      chunk_count: documents.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0),
    })
    if (path === '/api/ask') {
      const body = request.postDataJSON() as Record<string, unknown>
      askBodies.push(body)
      if (String(body.question).includes('Kubernetes')) {
        const base = answerFixture()
        return json(answerFixture({
          answer: '根据当前知识库资料，无法确定。',
          citations: [], confidence: 0,
          trust: { ...base.trust!, level: 'weak', label: '证据不足', reason: '没有达到拒答阈值的证据。', evidence_count: 0, source_count: 0, coverage: 0 },
          citation_audit: { ...base.citation_audit!, coverage: 0, supported_sentence_count: 0, grounding: 0 },
          retrieval_trace: {
            ...base.retrieval_trace,
            returned: 0,
            refusal_reason: 'no_evidence',
            pipeline: {
              ...base.retrieval_trace.pipeline,
              decision: { status: 'refused', reason: 'no_evidence', threshold: 0.05, confidence: 0 },
              citation_audit: { coverage: 0, grounding: 0, status: 'skipped' },
            },
          },
        }))
      }
      return json(answerFixture())
    }
    if (path.startsWith('/api/chunks/')) return json({
      found: true, chunk_id: 'doc-1:0', document_id: 'doc-1', filename: 'quality-guide.md',
      page_number: 1, heading_path: ['评测'],
      context: [{ id: 'doc-1:0', index: 0, text: '相邻上下文：固定黄金集覆盖回归阈值。', page_number: 1, heading_path: ['评测'], is_current: true }],
    })
    if (path === '/api/feedback' && method === 'POST') {
      evalDrafts = [{ id: 'eval-1', question: 'RAG 如何评测？', failure_type: 'bad_answer', status: 'draft' }]
      return json({ feedback: {}, eval_case: evalDrafts[0], stats: { total: 1, positive: 0, negative: 1, failure_types: { bad_answer: 1 }, recent: [] } })
    }
    if (path === '/api/metrics') return json(metricsFixture)
    if (path === '/api/history') return json({ history: [] })
    if (path === '/api/operations') return json({ operations: [] })
    if (path === '/api/knowledge/cards') return json({ cards: [] })
    if (path === '/api/eval/drafts') return json({ drafts: evalDrafts })
    return json({ detail: `Unhandled offline route: ${method} ${path}` }, 404)
  })

  return { askBodies }
}

test('upload, URL import, grounded answer, citation and feedback draft', async ({ page }) => {
  const api = await installOfflineApi(page)
  await page.goto('/')

  await page.getByTestId('file-input').setInputFiles({
    name: 'quality-guide.md', mimeType: 'text/markdown', buffer: Buffer.from('# 评测\nRecall@K 与 MRR。'),
  })
  await page.getByTestId('upload-button').click()
  await expect(page.getByText('quality-guide.md', { exact: true })).toBeVisible()

  await page.getByTestId('url-input').fill('https://example.com/guide')
  await page.getByTestId('url-import-button').click()
  await expect(page.getByText('example.com-guide.html', { exact: true })).toBeVisible()

  await page.getByRole('textbox', { name: '问题' }).fill('RAG 如何评测？')
  await page.getByTestId('run-query').click()
  await expect(page.getByRole('status')).toContainText('回答已生成')
  await expect(page.getByText('RAG 使用固定黄金集评测召回和引用质量。[1]')).toBeVisible()

  await page.getByTestId('citation-1').click()
  await expect(page.getByText('相邻上下文：固定黄金集覆盖回归阈值。')).toBeVisible()

  await page.getByTestId('feedback-down').click()
  await expect(page.getByText('已生成评测草稿')).toBeVisible()
  expect(api.askBodies).toHaveLength(1)
})

test('expert parameters and no-evidence refusal are explicit', async ({ page }) => {
  const api = await installOfflineApi(page)
  await page.goto('/')

  await page.getByTestId('mode-expert').click()
  await page.locator('input[name="candidate-k"]').fill('40')
  await page.getByRole('textbox', { name: '问题' }).fill('资料里有 Kubernetes 配置吗？')
  await page.getByTestId('run-query').click()

  await expect(page.getByRole('status')).toContainText('已安全拒答')
  await expect(page.getByText('没有可引用证据')).toBeVisible()
  await expect(page.locator('[data-stage="decision"]')).toContainText('回答决策')
  await expect(page.locator('[data-stage="decision"]')).toContainText('拒绝回答')
  expect(api.askBodies[0]).toMatchObject({ candidate_k: 40, question: '资料里有 Kubernetes 配置吗？' })
})
