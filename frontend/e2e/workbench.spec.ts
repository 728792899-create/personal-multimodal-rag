import { expect, test, type Page } from '@playwright/test'

import { answerFixture, metricsFixture, overviewFixture } from '../src/test/fixtures'


async function installOfflineApi(page: Page) {
  const documents: Array<Record<string, unknown>> = []
  const askBodies: Array<Record<string, unknown>> = []
  let evalDrafts: Array<Record<string, unknown>> = []
  let conversations: Array<Record<string, unknown>> = []
  let knowledgeBases: Array<Record<string, unknown>> = [
    { id: 'default', name: '默认知识库', description: '', is_default: true, document_count: 0, created_at: '', updated_at: '' },
  ]
  let jobs: Array<Record<string, unknown>> = []
  let queryAssets: Array<Record<string, unknown>> = []
  let sources: Array<Record<string, unknown>> = []
  let syncRuns: Array<Record<string, unknown>> = []

  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const json = async (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (path === '/api/auth/session') {
      return json({ session: { required: false, authenticated: false, user_id: '', workspace_id: '', role: '', csrf_token: '', expires_at: '' } })
    }
    if (path === '/api/sources' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      const source = {
        id: 'source-1',
        knowledge_base_id: body.knowledge_base_id,
        type: body.type,
        name: body.name,
        config: body.config,
        enabled: true,
        item_count: 0,
        deletion_candidate_count: 0,
        created_at: '',
        updated_at: '',
      }
      sources = [source]
      return json({ source }, 201)
    }
    if (path === '/api/sources') return json({
      sources,
      capabilities: {
        types: ['local_directory', 'rss_atom', 'url_list'],
        directory_roots: [{ id: 'root-demo', label: 'sources' }],
      },
    })
    if (path === '/api/sources/source-1/sync' && method === 'POST') {
      const run = {
        id: 'sync-1', source_id: 'source-1', status: 'succeeded', discovered: 2,
        unchanged: 1, updated: 1, deletion_candidates: 0, failed: 0,
        partial: false, empty_result: false, error_message: '', started_at: '', completed_at: '',
      }
      syncRuns = [run]
      sources = sources.map((item) => ({ ...item, item_count: 2 }))
      return json({ sync_run: run, accepted: true }, 202)
    }
    if (path === '/api/sync-runs') return json({ sync_runs: syncRuns })
    if (path === '/api/query-assets' && method === 'POST') {
      const asset = { id: 'query-1', filename: 'diagram.png', media_type: 'image/png', size_bytes: 96, width: 32, height: 24, expires_at: '2099-01-01T00:00:00', preview_url: '/api/assets/query-1' }
      queryAssets = [asset]
      return json({ assets: queryAssets }, 201)
    }
    if (path === '/api/query-assets/query-1' && method === 'DELETE') {
      queryAssets = []
      return json({ deleted: true, id: 'query-1' })
    }
    if (path === '/api/assets/query-1') {
      return route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('89504e470d0a1a0a', 'hex') })
    }

    if (path === '/api/knowledge-bases' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      const created = { id: 'kb-research', name: body.name, description: '', is_default: false, document_count: 0, created_at: '', updated_at: '' }
      knowledgeBases.push(created)
      return json({ knowledge_base: created }, 201)
    }
    if (path === '/api/knowledge-bases') return json({ knowledge_bases: knowledgeBases })
    if (path.endsWith('/graph')) return json({
      knowledge_base_id: 'default',
      nodes: [
        { node_id: 'entity:a', knowledge_base_id: 'default', type: 'entity', label: 'Alpha', normalized_label: 'alpha', document_id: null, element_id: null, properties: {} },
        { node_id: 'entity:b', knowledge_base_id: 'default', type: 'entity', label: 'Beta', normalized_label: 'beta', document_id: null, element_id: null, properties: {} },
      ],
      edges: [{ edge_id: 'edge:1', knowledge_base_id: 'default', source_node_id: 'entity:a', target_node_id: 'entity:b', relation: 'uses', document_id: 'doc-1', evidence_element_ids: ['element-1'], evidence_span: 'Alpha uses Beta', confidence: 1, extraction_version: 'native-graph-v1', properties: {} }],
      summary: { node_count: 2, edge_count: 1, evidence_element_count: 1, extraction_version: 'native-graph-v1' },
    })
    if (path === '/api/ingestions/file' && method === 'POST') {
      const doc = {
        id: 'doc-upload', filename: 'quality-guide.md', source_type: 'markdown', chunk_count: 2,
        char_count: 180, metadata: { index_status: 'indexed' }, quality: { score: 92 },
      }
      documents.push(doc)
      const job = { id: 'job-upload', source_type: 'file', source_name: 'quality-guide.md', knowledge_base_id: 'default', status: 'succeeded', stage: 'complete', progress: 100, attempts: 1, max_attempts: 3, cancel_requested: false, deduped: false, error_code: '', error_message: '', document_id: 'doc-upload', created_at: '', updated_at: '', started_at: '', completed_at: '' }
      jobs.unshift(job)
      return json({ job }, 202)
    }
    if (path === '/api/ingestions/url' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      if (String(body.url).includes('fail.example')) {
        const failed = { id: 'job-failed', source_type: 'url', source_name: 'fail.example', knowledge_base_id: 'default', status: 'failed', stage: 'failed', progress: 20, attempts: 3, max_attempts: 3, cancel_requested: false, deduped: false, error_code: 'INGESTION_FAILED', error_message: '模拟解析失败', document_id: '', created_at: '', updated_at: '', started_at: '', completed_at: '' }
        jobs.unshift(failed)
        return json({ job: failed }, 202)
      }
      const doc = {
        id: 'doc-url', filename: 'example.com-guide.html', source_type: 'url', chunk_count: 1,
        char_count: 80, metadata: { index_status: 'indexed' }, quality: { score: 84 },
      }
      documents.push(doc)
      const job = { id: 'job-url', source_type: 'url', source_name: 'example.com', knowledge_base_id: 'default', status: 'succeeded', stage: 'complete', progress: 100, attempts: 1, max_attempts: 3, cancel_requested: false, deduped: false, error_code: '', error_message: '', document_id: 'doc-url', created_at: '', updated_at: '', started_at: '', completed_at: '' }
      jobs.unshift(job)
      return json({ job }, 202)
    }
    if (path === '/api/index-jobs/job-failed/retry' && method === 'POST') {
      const recovered = { ...jobs.find((item) => item.id === 'job-failed'), status: 'succeeded', stage: 'complete', progress: 100, attempts: 1, error_code: '', error_message: '', document_id: 'doc-recovered' }
      jobs = [recovered, ...jobs.filter((item) => item.id !== 'job-failed')]
      return json({ job: recovered })
    }
    if (path === '/api/index-jobs') return json({ jobs })
    if (path === '/api/documents') return json({ documents })
    if (path === '/api/knowledge/overview') return json({
      ...overviewFixture,
      document_count: documents.length,
      chunk_count: documents.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0),
    })
    if (path === '/api/providers/status') return json({ status: 'ready', environment: 'test', fallback_allowed: true, providers: { answer: { provider: 'template', configured: true, mode: 'offline', capabilities: ['answer'] }, embedding: { provider: 'mock', configured: true, mode: 'offline', capabilities: ['embeddings'] }, vector_store: { provider: 'memory', configured: true } } })
    if (path === '/api/conversations' && method === 'POST') {
      const conversation = { id: 'conv-1', title: '新会话', knowledge_base_ids: ['default'], message_count: 0, created_at: '', updated_at: '' }
      conversations = [conversation]
      return json({ conversation }, 201)
    }
    if (path === '/api/conversations') return json({ conversations })
    if (path === '/api/conversations/conv-1/messages') return json({ messages: [] })
    if (path === '/api/conversations/conv-1/messages:stream') {
      const body = request.postDataJSON() as Record<string, unknown>
      askBodies.push(body)
      let response = answerFixture()
      if (String(body.question).includes('Kubernetes')) {
        const base = answerFixture()
        response = answerFixture({
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
        })
      }
      const events = [
        ...(Array.isArray(body.attachments) && body.attachments.length
          ? [
            { type: 'query.enrichment.started', attachment_count: body.attachments.length },
            { type: 'query.enrichment.completed', attachments: queryAssets.map((item) => ({ ...item, detail: 'high', description: 'Alpha uses Beta', keywords: ['Alpha', 'Beta'], ocr_status: 'ok', provider: 'template' })), provider: 'template' },
          ] : []),
        { type: 'retrieval.started', context_message_count: 0 },
        { type: 'retrieval.completed', citations: response.citations, retrieval_trace: response.retrieval_trace, confidence: response.confidence, diagnostics: response.diagnostics },
        ...(response.retrieval_trace.refusal_reason
          ? [{ type: 'refusal', response }]
          : [{ type: 'answer.delta', delta: response.answer }, { type: 'answer.completed', response }]),
        { type: 'done', status: 'completed' },
      ]
      const stream = events.map((event, index) => `event: ${event.type}\ndata: ${JSON.stringify({ request_id: 'req', conversation_id: 'conv-1', message_id: 'msg', sequence: index + 1, ...event })}\n\n`).join('')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: stream })
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
  await expect(page.getByRole('button', { name: /quality-guide\.md markdown/ })).toBeVisible()

  await page.getByTestId('url-input').fill('https://example.com/guide')
  await page.getByTestId('url-import-button').click()
  await expect(page.getByRole('button', { name: /example\.com-guide\.html url/ })).toBeVisible()

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

test('knowledge-base creation, narrow layout and failed job retry stay usable', async ({ page }) => {
  await installOfflineApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByText('Provider ready')).toBeVisible()
  await page.locator('.inline-create input').fill('研究资料')
  await page.locator('form.inline-create button').click()
  await expect(page.locator('#knowledge-base-select')).toHaveValue('kb-research')

  await page.locator('#knowledge-base-select').selectOption('default')
  await page.getByTestId('url-input').fill('https://fail.example/guide')
  await page.getByTestId('url-import-button').click()
  await expect(page.getByRole('alert')).toContainText('模拟解析失败')

  const taskSection = page.locator('details.task-section')
  if (!(await taskSection.getAttribute('open'))) await taskSection.locator('summary').click()
  await taskSection.getByRole('button', { name: '重试' }).click()
  await expect(taskSection.getByText('succeeded')).toBeVisible()
  await expect(page.locator('#main-workspace')).toBeVisible()
})

test('image question, graph controls and accessible graph evidence stay connected', async ({ page }) => {
  const api = await installOfflineApi(page)
  await page.goto('/')

  await page.getByTestId('query-image-input').setInputFiles({
    name: 'diagram.png', mimeType: 'image/png', buffer: Buffer.from('fixture-image'),
  })
  await expect(page.getByText('diagram.png')).toBeVisible()
  await page.locator('.attachment-detail select').selectOption('high')
  await page.getByRole('textbox', { name: '问题' }).fill('图中 Alpha 如何连到 Beta？')
  await page.getByTestId('run-query').click()
  await expect(page.getByRole('status')).toContainText('回答已生成')
  expect(api.askBodies[0]).toMatchObject({ attachments: [{ id: 'query-1', detail: 'high' }], strategy: 'auto' })

  await page.getByTestId('mode-expert').click()
  await page.locator('select[name="retrieval-strategy"]').selectOption('hybrid_graph')
  await page.locator('input[name="graph-hops"]').fill('2')
  await page.getByRole('tab', { name: '图谱' }).click()
  await expect(page.getByRole('heading', { name: '证据图谱' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('Alpha uses Beta')
})

test('session bootstrap failure exposes a retry and recovers the workbench', async ({ page }) => {
  await installOfflineApi(page)
  let attempts = 0
  await page.route('**/api/auth/session', async (route) => {
    attempts += 1
    if (attempts === 1) {
      await route.abort('connectionfailed')
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: {
          required: false,
          authenticated: false,
          user_id: '',
          workspace_id: '',
          role: '',
          csrf_token: '',
          expires_at: '',
        },
      }),
    })
  })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '无法确认工作区会话' })).toBeVisible()
  await page.getByRole('button', { name: '重试连接' }).click()

  await expect(page.getByTestId('file-input')).toBeAttached()
  expect(attempts).toBe(2)
})

test('session authentication gates the workbench and logout revokes access', async ({ page }) => {
  await installOfflineApi(page)
  let authenticated = false
  let csrfSeen = false
  await page.route('**/api/auth/session', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: {
          required: true,
          authenticated,
          user_id: authenticated ? 'owner' : '',
          workspace_id: authenticated ? 'default' : '',
          role: authenticated ? 'owner' : '',
          csrf_token: authenticated ? 'csrf-test' : '',
          expires_at: authenticated ? '2099-01-01T00:00:00' : '',
        },
      }),
    })
  })
  await page.route('**/api/auth/login', async (route) => {
    authenticated = route.request().postDataJSON().password === 'correct password'
    await route.fulfill({
      status: authenticated ? 200 : 401,
      contentType: 'application/json',
      body: JSON.stringify(authenticated
        ? { session: { required: true, authenticated: true, user_id: 'owner', workspace_id: 'default', role: 'owner', csrf_token: 'csrf-test', expires_at: '2099-01-01T00:00:00' } }
        : { detail: 'Invalid administrator credentials' }),
    })
  })
  await page.route('**/api/auth/logout', async (route) => {
    csrfSeen = route.request().headers()['x-csrf-token'] === 'csrf-test'
    authenticated = false
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ logged_out: true }),
    })
  })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Personal Multimodal RAG' })).toBeVisible()
  await page.getByLabel('管理员密码').fill('correct password')
  await page.getByRole('button', { name: '登录工作台' }).click()
  await expect(page.getByTestId('file-input')).toBeAttached()

  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByRole('button', { name: '登录工作台' })).toBeVisible()
  expect(csrfSeen).toBe(true)
})

test('URL source subscription creates and reports an incremental sync', async ({ page }) => {
  await installOfflineApi(page)
  await page.goto('/')

  const manager = page.getByTestId('source-manager')
  await manager.locator('summary').click()
  await manager.locator('input[name="source-name"]').fill('产品资料订阅')
  await manager.locator('textarea[name="source-urls"]').fill('https://example.com/guide\nhttps://example.com/changelog')
  await manager.getByRole('button', { name: '添加数据源' }).click()

  await expect(manager.getByText('产品资料订阅')).toBeVisible()
  await manager.getByRole('button', { name: '立即同步' }).click()
  await expect(manager.getByText(/最近同步：succeeded/)).toBeVisible()
  await expect(manager.getByText('新增/更新 1')).toBeVisible()
})
