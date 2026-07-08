<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  askQuestion,
  clearHistory,
  compareSearchStrategies,
  createEvalCase,
  deleteDocument,
  getSystemMetrics,
  getKnowledgeOverview,
  getDocumentDetail,
  getChunkContext,
  importUrl,
  listOperations,
  listDocuments,
  listEvalDrafts,
  listHistory,
  listKnowledgeCards,
  rebuildAllDocuments,
  rebuildDocument,
  rewriteAnswer,
  runEvalDrafts,
  searchDocuments,
  saveKnowledgeCard,
  submitFeedback,
  uploadDocument,
  type AskResponse,
  type ChunkResult,
  type ChunkContext,
  type DiagnosticAction,
  type DocumentDetail,
  type DocumentMeta,
  type EvalDraft,
  type EvaluationResult,
  type FeedbackStats,
  type HistoryItem,
  type KnowledgeCard,
  type KnowledgeOverview,
  type OperationLog,
  type RetrievalOptions,
  type RewriteResponse,
  type RewriteStyle,
  type SearchCompareResponse,
  type SystemMetrics,
} from './api'

type WorkMode = 'answer' | 'search'
type AppMode = 'user' | 'expert'
type SearchMode = 'hybrid' | 'keyword' | 'semantic'
type SearchProfile = 'balanced' | 'precision' | 'recall'
type InspectorTab = 'trace' | 'document'

const documents = ref<DocumentMeta[]>([])
const history = ref<HistoryItem[]>([])
const overview = ref<KnowledgeOverview | null>(null)
const operations = ref<OperationLog[]>([])
const cards = ref<KnowledgeCard[]>([])
const evalDrafts = ref<EvalDraft[]>([])
const metrics = ref<SystemMetrics | null>(null)
const selectedDocument = ref<DocumentDetail | null>(null)
const selectedFile = ref<File | null>(null)
const urlToImport = ref('')
const importingUrl = ref(false)
const evalQuestion = ref('')
const evalKeywords = ref('')
const evalRunning = ref(false)
const evalResults = ref<EvaluationResult[]>([])
const question = ref('如何优化 RAG 的召回质量？')
const topK = ref(5)
const candidateK = ref(24)
const vectorBalance = ref(0.38)
const mmrLambda = ref(0.78)
const minScore = ref(0.05)
const queryRewrite = ref(true)
const appMode = ref<AppMode>('user')
const workMode = ref<WorkMode>('answer')
const searchMode = ref<SearchMode>('hybrid')
const searchProfile = ref<SearchProfile>('balanced')
const scopedDocumentIds = ref<string[]>([])
const documentFilter = ref('')
const historyFilter = ref('')
const inspectorTab = ref<InspectorTab>('trace')
const loading = ref(false)
const uploading = ref(false)
const rebuildingId = ref('')
const loadingDocument = ref(false)
const error = ref('')
const answer = ref<AskResponse | null>(null)
const selectedCitation = ref<ChunkResult | null>(null)
const compareResult = ref<SearchCompareResponse | null>(null)
const copied = ref(false)
const comparing = ref(false)
const feedbackText = ref('')
const feedbackMessage = ref('')
const feedbackSubmitting = ref(false)
const feedbackStats = ref<FeedbackStats | null>(null)
const rewriteResult = ref<RewriteResponse | null>(null)
const rewriting = ref(false)
const cardMessage = ref('')
const citationContext = ref<ChunkContext | null>(null)
const loadingContext = ref(false)

const questionPresets = [
  '如何优化 RAG 的召回质量？',
  '这份资料有没有提到 Redis 集群配置？',
  '王文通有哪些和 AI 工作流相关的项目经历？',
]

const demoQuestions = [
  '这个 RAG 项目最适合写进简历的技术亮点是什么？',
  '如果面试官追问引用可信度，这个系统怎么降低幻觉？',
  '这份资料有没有提到 Kubernetes 部署？',
  '杭州 AIGC 应用开发岗位更看重哪些能力？',
]

const totalChunks = computed(() => documents.value.reduce((sum, item) => sum + item.chunk_count, 0))
const totalChars = computed(() => documents.value.reduce((sum, item) => sum + item.char_count, 0))
const avgQualityLabel = computed(() => (overview.value ? Number(overview.value.avg_quality_score || 0).toFixed(1) : '-'))
const bm25Weight = computed(() => Number((1 - vectorBalance.value).toFixed(2)))
const vectorWeight = computed(() => Number(vectorBalance.value.toFixed(2)))
const scopeSet = computed(() => new Set(scopedDocumentIds.value))
const filteredDocuments = computed(() => {
  const keyword = documentFilter.value.trim().toLowerCase()
  if (!keyword) return documents.value
  return documents.value.filter((doc) => doc.filename.toLowerCase().includes(keyword) || doc.source_type.includes(keyword))
})
const filteredHistory = computed(() => {
  const keyword = historyFilter.value.trim().toLowerCase()
  if (!keyword) return history.value
  return history.value.filter((item) => item.question.toLowerCase().includes(keyword) || item.answer.toLowerCase().includes(keyword))
})
const scopeLabel = computed(() => {
  if (scopedDocumentIds.value.length === 0) return '全部文档'
  return `${scopedDocumentIds.value.length} 个文档`
})
const providerLabel = computed(() => {
  const trace = answer.value?.retrieval_trace
  if (!trace) return '未运行'
  return `${trace.embedding_provider || '-'} / ${trace.vector_store || '-'}`
})
const confidenceLabel = computed(() => {
  if (answer.value?.confidence === null || answer.value?.confidence === undefined) return '-'
  return Number(answer.value.confidence).toFixed(4)
})
const runLabel = computed(() => (workMode.value === 'answer' ? '检索并回答' : '只检索证据'))
const hasResult = computed(() => Boolean(answer.value))
const diagnostics = computed(() => answer.value?.diagnostics ?? [])
const repairActions = computed(() => diagnostics.value.flatMap((item) => item.actions ?? []))
const trust = computed(() => answer.value?.trust)
const citationAudit = computed(() => answer.value?.citation_audit)
const gapReport = computed(() => answer.value?.gap_report)
const queryAnalysis = computed(() => answer.value?.retrieval_trace.query_analysis)
const pipelineSteps = computed(() => {
  const trace = answer.value?.retrieval_trace
  return [
    { label: 'Query', value: queryAnalysis.value?.label || '待识别', active: Boolean(trace) },
    { label: 'Recall', value: trace ? `${trace.raw_candidates ?? 0} 条` : '待检索', active: Boolean(trace?.raw_candidates) },
    { label: 'MMR', value: trace ? `${trace.mmr_selected ?? 0} 条` : '待去冗余', active: Boolean(trace?.mmr_selected) },
    { label: 'Rerank', value: trace?.rerank_status || '待重排', active: Boolean(trace?.rerank_status) },
    { label: 'Audit', value: trust.value?.label || '待审计', active: Boolean(trust.value) },
  ]
})

function buildRetrievalOptions(): RetrievalOptions {
  if (appMode.value === 'user') {
    return {
      top_k: 5,
      candidate_k: 24,
      search_mode: 'hybrid',
      search_profile: 'balanced',
      document_ids: scopedDocumentIds.value,
      bm25_weight: 0.62,
      vector_weight: 0.38,
      mmr_lambda: 0.78,
      min_score: 0.05,
      query_rewrite: true,
      rerank_enabled: true,
    }
  }
  return {
    top_k: topK.value,
    candidate_k: candidateK.value,
    search_mode: searchMode.value,
    search_profile: searchProfile.value,
    document_ids: scopedDocumentIds.value,
    bm25_weight: bm25Weight.value,
    vector_weight: vectorWeight.value,
    mmr_lambda: mmrLambda.value,
    min_score: minScore.value,
    query_rewrite: queryRewrite.value,
    rerank_enabled: true,
  }
}

async function refreshDocuments() {
  documents.value = await listDocuments()
  overview.value = await getKnowledgeOverview()
  const existing = new Set(documents.value.map((doc) => doc.id))
  scopedDocumentIds.value = scopedDocumentIds.value.filter((id) => existing.has(id))
}

async function refreshHistory() {
  history.value = await listHistory()
}

async function refreshOperations() {
  operations.value = await listOperations(20)
}

async function refreshMetrics() {
  metrics.value = await getSystemMetrics()
}

async function refreshCards() {
  cards.value = await listKnowledgeCards(20)
}

async function refreshEvalDrafts() {
  evalDrafts.value = await listEvalDrafts(20)
}

async function handleUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  error.value = ''
  try {
    await uploadDocument(selectedFile.value)
    selectedFile.value = null
    await refreshDocuments()
    await refreshOperations()
    await refreshMetrics()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function handleImportUrl() {
  if (!urlToImport.value.trim()) return
  importingUrl.value = true
  error.value = ''
  try {
    await importUrl(urlToImport.value.trim())
    urlToImport.value = ''
    await refreshDocuments()
    await refreshOperations()
    await refreshMetrics()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'URL 导入失败'
  } finally {
    importingUrl.value = false
  }
}

async function handleRun() {
  if (!question.value.trim()) return
  loading.value = true
  error.value = ''
  copied.value = false
  feedbackText.value = ''
  feedbackMessage.value = ''
  rewriteResult.value = null
  cardMessage.value = ''
  citationContext.value = null
  try {
    compareResult.value = null
    const options = buildRetrievalOptions()
    if (workMode.value === 'answer') {
      answer.value = await askQuestion(question.value, options)
      await refreshHistory()
    } else {
      const result = await searchDocuments(question.value, options)
      answer.value = {
        answer: '',
        citations: result.results,
        retrieval_trace: result.trace,
        generation_trace: {
          answer_provider: 'search-only',
          answer_model: '-',
          grounded: true,
          skipped: true,
          citation_count: result.results.length,
        },
        confidence: result.results[0]?.rerank_score ?? result.results[0]?.score ?? 0,
        diagnostics: result.diagnostics,
        trust: {
          level: result.results.length ? 'medium' : 'unknown',
          label: result.results.length ? '证据列表' : '无法确定',
          reason: result.results.length ? '当前处于只检索模式，请人工查看证据后判断。' : '未检索到证据。',
          evidence_count: result.results.length,
          source_count: new Set(result.results.map((item) => item.document_id)).size,
          top_score: result.results[0]?.rerank_score ?? result.results[0]?.score ?? 0,
          confidence: result.results[0]?.rerank_score ?? result.results[0]?.score ?? 0,
          coverage: 0,
          recommendations: ['只检索模式不会生成答案，适合先做证据核查。'],
        },
        citation_audit: {
          coverage: 0,
          sentence_count: 0,
          supported_sentence_count: 0,
          unsupported_sentence_count: 0,
          unsupported_claims: [],
          checked: true,
        },
        gap_report: {
          query_intent: {
            intent: 'search',
            label: '证据搜索',
            matched_terms: [],
            query_terms: [],
            recommended: {
              search_profile: 'balanced',
              search_mode: 'hybrid',
              candidate_k: 24,
              reason: '只检索模式由当前控制项决定。',
            },
          },
          missing_topics: [],
          failure_types: {},
          needs_action: result.results.length === 0,
          suggestions: result.results.length ? ['当前处于只检索模式，可打开引用上下文核验证据。'] : ['没有检索到证据，建议扩大范围或补充资料。'],
          created_at: new Date().toISOString(),
        },
      }
    }
    selectedCitation.value = answer.value.citations[0] ?? null
    inspectorTab.value = 'trace'
    await refreshOperations()
    await refreshMetrics()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '请求失败'
  } finally {
    loading.value = false
  }
}

async function handleCreateEvalCase() {
  if (!evalQuestion.value.trim()) return
  error.value = ''
  try {
    const keywords = evalKeywords.value
      .split(/[,，\s]+/)
      .map((item) => item.trim())
      .filter(Boolean)
    await createEvalCase(evalQuestion.value.trim(), keywords)
    evalQuestion.value = ''
    evalKeywords.value = ''
    await refreshEvalDrafts()
    await refreshOperations()
    await refreshMetrics()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建评测 case 失败'
  }
}

async function handleRunEvalDrafts() {
  evalRunning.value = true
  error.value = ''
  try {
    const result = await runEvalDrafts(50)
    evalResults.value = result.results
    await refreshOperations()
    await refreshMetrics()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '运行评测失败'
  } finally {
    evalRunning.value = false
  }
}

async function handleCompare() {
  if (!question.value.trim()) return
  comparing.value = true
  error.value = ''
  try {
    compareResult.value = await compareSearchStrategies(question.value, buildRetrievalOptions())
  } catch (err) {
    error.value = err instanceof Error ? err.message : '策略对比失败'
  } finally {
    comparing.value = false
  }
}

async function handleDelete(documentId: string) {
  if (!window.confirm('确认删除这份文档及其索引吗？')) return
  error.value = ''
  try {
    await deleteDocument(documentId)
    scopedDocumentIds.value = scopedDocumentIds.value.filter((id) => id !== documentId)
    await refreshDocuments()
    if (selectedDocument.value?.document.id === documentId) {
      selectedDocument.value = null
    }
    if (selectedCitation.value?.document_id === documentId) {
      selectedCitation.value = null
    }
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}

async function handleRebuild(documentId: string) {
  rebuildingId.value = documentId
  error.value = ''
  try {
    await rebuildDocument(documentId)
    await refreshDocuments()
    selectedDocument.value = await getDocumentDetail(documentId)
    inspectorTab.value = 'document'
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重建索引失败'
  } finally {
    rebuildingId.value = ''
  }
}

async function handleRebuildAll() {
  if (!window.confirm('确认重建全部文档索引吗？这可能需要一些时间。')) return
  rebuildingId.value = 'all'
  error.value = ''
  try {
    await rebuildAllDocuments()
    await refreshDocuments()
    if (selectedDocument.value) {
      selectedDocument.value = await getDocumentDetail(selectedDocument.value.document.id)
    }
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重建全部索引失败'
  } finally {
    rebuildingId.value = ''
  }
}

async function handleSelectDocument(documentId: string) {
  loadingDocument.value = true
  error.value = ''
  try {
    selectedDocument.value = await getDocumentDetail(documentId)
    inspectorTab.value = 'document'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '获取文档详情失败'
  } finally {
    loadingDocument.value = false
  }
}

function handleSelectHistory(item: HistoryItem) {
  appMode.value = 'user'
  workMode.value = 'answer'
  question.value = item.question
  answer.value = item
  selectedCitation.value = item.citations[0] ?? null
  inspectorTab.value = 'trace'
  feedbackText.value = ''
  feedbackMessage.value = ''
}

async function handleClearHistory() {
  if (!window.confirm('确认清空全部问答历史吗？')) return
  error.value = ''
  try {
    await clearHistory()
    history.value = []
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '清空历史失败'
  }
}

async function handleFeedback(rating: 'up' | 'down', failureType?: 'wrong_citation' | 'unsupported_claim' | 'bad_answer' | 'retrieval_miss') {
  if (!answer.value) return
  feedbackSubmitting.value = true
  feedbackMessage.value = ''
  error.value = ''
  try {
    const result = await submitFeedback({
      history_id: answer.value.history_id,
      question: question.value,
      answer: answer.value.answer,
      rating,
      feedback_text: feedbackText.value,
      failure_type: rating === 'down' ? failureType || 'bad_answer' : undefined,
      citations: answer.value.citations,
    })
    feedbackStats.value = result.stats
    feedbackMessage.value = rating === 'up' ? '已记录为有效回答' : '已生成评测草稿'
    feedbackText.value = ''
    await refreshEvalDrafts()
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '提交反馈失败'
  } finally {
    feedbackSubmitting.value = false
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
}

function toggleDocumentScope(documentId: string) {
  if (scopeSet.value.has(documentId)) {
    scopedDocumentIds.value = scopedDocumentIds.value.filter((id) => id !== documentId)
  } else {
    scopedDocumentIds.value = [...scopedDocumentIds.value, documentId]
  }
}

function setOnlyDocumentScope(documentId: string) {
  scopedDocumentIds.value = [documentId]
}

function clearScope() {
  scopedDocumentIds.value = []
}

function applyPreset(text: string) {
  question.value = text
}

function resetRetrievalControls() {
  topK.value = 5
  candidateK.value = 24
  vectorBalance.value = 0.38
  mmrLambda.value = 0.78
  minScore.value = 0.05
  queryRewrite.value = true
  searchMode.value = 'hybrid'
  searchProfile.value = 'balanced'
}

async function handleDiagnosticAction(action: DiagnosticAction) {
  const payload = action.payload || {}
  if (action.id === 'open_expert_trace') {
    appMode.value = 'expert'
    inspectorTab.value = 'trace'
    return
  }
  if (action.id === 'view_evidence_only') {
    workMode.value = 'search'
    await handleRun()
    return
  }
  if (action.id === 'rebuild_all_indexes') {
    await handleRebuildAll()
    return
  }
  if (Array.isArray(payload.document_ids)) {
    scopedDocumentIds.value = payload.document_ids as string[]
  }
  if (typeof payload.min_score === 'number') {
    minScore.value = payload.min_score
  }
  if (typeof payload.candidate_k_multiplier === 'number') {
    candidateK.value = Math.min(80, Math.max(candidateK.value * payload.candidate_k_multiplier, 12))
  }
  if (payload.search_mode === 'hybrid' || payload.search_mode === 'keyword' || payload.search_mode === 'semantic') {
    searchMode.value = payload.search_mode
  }
  if (payload.search_profile === 'balanced' || payload.search_profile === 'precision' || payload.search_profile === 'recall') {
    searchProfile.value = payload.search_profile
  }
  appMode.value = 'expert'
  await handleRun()
}

async function copyAnswer() {
  if (!answer.value?.answer) return
  await navigator.clipboard.writeText(answer.value.answer)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1200)
}

async function handleRewrite(style: RewriteStyle) {
  if (!answer.value?.answer) return
  rewriting.value = true
  error.value = ''
  try {
    rewriteResult.value = await rewriteAnswer(question.value, answer.value.answer, style, answer.value.citations)
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '答案改写失败'
  } finally {
    rewriting.value = false
  }
}

async function handleSaveCard() {
  if (!answer.value?.answer) return
  cardMessage.value = ''
  error.value = ''
  try {
    await saveKnowledgeCard(question.value, answer.value.answer, answer.value.citations)
    cardMessage.value = '已保存知识卡片'
    await refreshCards()
    await refreshOperations()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存知识卡片失败'
  }
}

async function handleLoadContext(item: ChunkResult) {
  selectedCitation.value = item
  loadingContext.value = true
  error.value = ''
  try {
    citationContext.value = await getChunkContext(item.id, 1)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '获取引用上下文失败'
  } finally {
    loadingContext.value = false
  }
}

function scoreWidth(item: ChunkResult) {
  const score = Math.max(0, Math.min(1, item.rerank_score || item.score || 0))
  return `${Math.round(score * 100)}%`
}

function percentLabel(value?: number) {
  return `${Math.round(Math.max(0, Math.min(1, value || 0)) * 100)}%`
}

function qualityBadgeClass(score?: number) {
  if ((score ?? 0) >= 85) return 'good'
  if ((score ?? 0) >= 70) return 'ok'
  if ((score ?? 0) >= 50) return 'warn'
  return 'bad'
}

function shortText(text: string, max = 180) {
  const cleaned = text.replace(/\s+/g, ' ').trim()
  return cleaned.length > max ? `${cleaned.slice(0, max)}...` : cleaned
}

async function bootDemoFromUrl() {
  const params = new URLSearchParams(window.location.search)
  const demoQuestion = params.get('question')
  if (demoQuestion) {
    question.value = demoQuestion
  }
  await refreshDocuments()
  await refreshHistory()
  await refreshOperations()
  await refreshCards()
  await refreshEvalDrafts()
  await refreshMetrics()
  if (params.get('autoAsk') === '1') {
    await handleRun()
  }
}

onMounted(bootDemoFromUrl)
</script>

<template>
  <main class="app-shell">
    <section class="topbar">
      <div class="brand-block">
        <p class="eyebrow">Personal Multimodal RAG</p>
        <h1>个人知识库检索工作台</h1>
      </div>
      <div class="app-mode-switch">
        <div class="segmented">
          <button :class="{ active: appMode === 'user' }" @click="appMode = 'user'; workMode = 'answer'">普通模式</button>
          <button :class="{ active: appMode === 'expert' }" @click="appMode = 'expert'">专家模式</button>
        </div>
      </div>
      <div class="metrics" aria-label="knowledge base metrics">
        <div>
          <span>{{ documents.length }}</span>
          <small>文档</small>
        </div>
        <div>
          <span>{{ totalChunks }}</span>
          <small>片段</small>
        </div>
        <div>
          <span>{{ totalChars }}</span>
          <small>字符</small>
        </div>
        <div>
          <span>{{ scopeLabel }}</span>
          <small>范围</small>
        </div>
        <div>
          <span>{{ avgQualityLabel }}</span>
          <small>质量分</small>
        </div>
      </div>
    </section>

    <section class="workspace">
      <aside class="panel sidebar">
        <div class="section-head">
          <div>
            <span class="section-kicker">Knowledge</span>
            <h2>知识源</h2>
          </div>
          <button v-if="scopedDocumentIds.length" class="ghost-btn" @click="clearScope">全部</button>
        </div>

        <label class="upload-box">
          <input type="file" accept=".pdf,.md,.markdown,.txt,.png,.jpg,.jpeg" @change="onFileChange" />
          <span class="upload-icon">+</span>
          <strong>{{ selectedFile?.name || '选择文件' }}</strong>
          <small>PDF / Markdown / Text / Image</small>
        </label>

        <button class="primary-btn" :disabled="!selectedFile || uploading" @click="handleUpload">
          <span v-if="uploading" class="spin text-icon">●</span>
          <span v-else class="text-icon">↑</span>
          上传并索引
        </button>

        <div class="url-import-box">
          <input v-model="urlToImport" class="compact-input" type="url" placeholder="粘贴 URL 导入网页资料" />
          <button class="ghost-btn" :disabled="importingUrl || !urlToImport.trim()" @click="handleImportUrl">
            {{ importingUrl ? '导入中' : '导入 URL' }}
          </button>
        </div>

        <div class="toolbar-row">
          <input v-model="documentFilter" class="compact-input" type="search" placeholder="筛选文档" />
          <button v-if="documents.length" class="ghost-btn" :disabled="rebuildingId === 'all'" @click="handleRebuildAll">
            重建
          </button>
        </div>

        <div class="doc-list">
          <article
            v-for="doc in filteredDocuments"
            :key="doc.id"
            class="doc-item"
            :class="{ active: selectedDocument?.document.id === doc.id, scoped: scopeSet.has(doc.id) }"
          >
            <button class="scope-dot" :aria-pressed="scopeSet.has(doc.id)" @click="toggleDocumentScope(doc.id)">
              <span></span>
            </button>
            <div class="doc-main" @click="handleSelectDocument(doc.id)">
              <strong>{{ doc.filename }}</strong>
              <span>{{ doc.source_type }} · {{ doc.chunk_count }} chunks · {{ doc.char_count }} chars</span>
              <span class="status-line">
                {{ doc.metadata.index_status || '-' }}
                <b :class="['quality-pill', qualityBadgeClass(doc.quality?.score)]">Q {{ doc.quality?.score ?? '-' }}</b>
              </span>
            </div>
            <div class="doc-actions">
              <button class="icon-btn" title="仅检索此文档" @click="setOnlyDocumentScope(doc.id)">◎</button>
              <button class="icon-btn" title="重建索引" :disabled="rebuildingId === doc.id" @click="handleRebuild(doc.id)">↻</button>
              <button class="icon-btn danger" title="删除文档" @click="handleDelete(doc.id)">×</button>
            </div>
          </article>
          <p v-if="filteredDocuments.length === 0" class="empty">暂无文档</p>
        </div>

        <div class="history-list">
          <div class="section-head compact">
            <div>
              <span class="section-kicker">History</span>
              <h3>问答历史</h3>
            </div>
            <button v-if="history.length" class="ghost-btn" @click="handleClearHistory">清空</button>
          </div>
          <input v-model="historyFilter" class="compact-input" type="search" placeholder="筛选历史" />
          <article v-for="item in filteredHistory" :key="item.id" class="history-item" @click="handleSelectHistory(item)">
            <strong>{{ item.question }}</strong>
            <span>{{ item.generation_trace.answer_provider || '-' }} · {{ item.confidence ?? 0 }}</span>
          </article>
          <p v-if="filteredHistory.length === 0" class="empty">暂无历史</p>
        </div>
      </aside>

      <section class="panel qa-panel">
        <div class="qa-header">
          <div>
            <span class="section-kicker">Retrieval</span>
            <h2>{{ appMode === 'user' ? '知识库问答' : (workMode === 'answer' ? '证据问答' : '证据搜索') }}</h2>
          </div>
          <div v-if="appMode === 'expert'" class="segmented">
            <button :class="{ active: workMode === 'answer' }" @click="workMode = 'answer'">问答</button>
            <button :class="{ active: workMode === 'search' }" @click="workMode = 'search'">搜索</button>
          </div>
          <span v-else class="mode-badge">自动检索</span>
        </div>

        <div class="query-box">
          <textarea
            v-model="question"
            rows="3"
            placeholder="输入问题"
            @keydown.meta.enter.prevent="handleRun"
            @keydown.ctrl.enter.prevent="handleRun"
          />
          <div class="preset-row">
            <button v-for="item in questionPresets" :key="item" class="chip-btn" @click="applyPreset(item)">
              {{ item }}
            </button>
          </div>
          <div class="demo-question-row">
            <button v-for="item in demoQuestions.slice(0, 3)" :key="item" class="chip-btn demo-chip" @click="applyPreset(item)">
              {{ item }}
            </button>
          </div>
        </div>

        <div class="retrieval-map">
          <article v-for="(step, index) in pipelineSteps" :key="step.label" :class="{ active: step.active }">
            <span>{{ index + 1 }}</span>
            <strong>{{ step.label }}</strong>
            <small>{{ step.value }}</small>
          </article>
        </div>

        <div v-if="appMode === 'user'" class="user-mode-card">
          <div>
            <strong>当前知识库：{{ scopeLabel }}</strong>
            <span>系统会自动使用混合检索、查询改写、重排和拒答判断。</span>
          </div>
          <button class="ghost-btn" @click="appMode = 'expert'">高级设置</button>
        </div>

        <div v-if="appMode === 'user' && overview" class="health-strip">
          <span>健康度 {{ avgQualityLabel }}</span>
          <span>{{ overview.quality_distribution.excellent }} 优秀</span>
          <span>{{ overview.quality_distribution.needs_work }} 待优化</span>
          <span v-if="metrics">拒答 {{ metrics.answering.no_answer_count }} / 兜底 {{ metrics.answering.fallback_count }}</span>
          <span v-if="overview.themes.length">主题：{{ overview.themes.slice(0, 4).join(' / ') }}</span>
        </div>

        <div v-else class="control-surface">
          <div class="control-grid">
            <label>
              <span>Top K</span>
              <input v-model.number="topK" min="1" max="12" type="range" />
              <strong>{{ topK }}</strong>
            </label>
            <label>
              <span>候选池</span>
              <input v-model.number="candidateK" min="3" max="80" step="1" type="range" />
              <strong>{{ candidateK }}</strong>
            </label>
            <label>
              <span>语义权重</span>
              <input v-model.number="vectorBalance" min="0" max="1" step="0.05" type="range" :disabled="searchMode !== 'hybrid'" />
              <strong>{{ vectorWeight }}</strong>
            </label>
            <label>
              <span>MMR</span>
              <input v-model.number="mmrLambda" min="0" max="1" step="0.01" type="range" />
              <strong>{{ mmrLambda }}</strong>
            </label>
            <label>
              <span>阈值</span>
              <input v-model.number="minScore" min="0" max="1" step="0.01" type="range" />
              <strong>{{ minScore }}</strong>
            </label>
          </div>

          <div class="strategy-row">
            <div class="segmented">
              <button :class="{ active: searchMode === 'hybrid' }" @click="searchMode = 'hybrid'">混合</button>
              <button :class="{ active: searchMode === 'keyword' }" @click="searchMode = 'keyword'">关键词</button>
              <button :class="{ active: searchMode === 'semantic' }" @click="searchMode = 'semantic'">语义</button>
            </div>
            <div class="segmented">
              <button :class="{ active: searchProfile === 'balanced' }" @click="searchProfile = 'balanced'">均衡</button>
              <button :class="{ active: searchProfile === 'precision' }" @click="searchProfile = 'precision'">精准</button>
              <button :class="{ active: searchProfile === 'recall' }" @click="searchProfile = 'recall'">召回</button>
            </div>
            <label class="toggle">
              <input v-model="queryRewrite" type="checkbox" />
              <span>Query Rewrite</span>
            </label>
            <button class="ghost-btn" @click="resetRetrievalControls">重置</button>
          </div>
        </div>

        <div class="run-row">
          <div class="run-meta">
            <span>{{ scopeLabel }}</span>
            <span v-if="queryAnalysis">{{ queryAnalysis.label }}</span>
            <template v-if="appMode === 'expert'">
              <span>BM25 {{ bm25Weight }} / Vector {{ vectorWeight }}</span>
              <span>{{ searchProfile }}</span>
            </template>
            <template v-else>
              <span>自动检索</span>
              <span>带引用回答</span>
            </template>
          </div>
          <button class="primary-btn run-btn" :disabled="loading || !question.trim()" @click="handleRun">
            <span v-if="loading" class="spin text-icon">●</span>
            <span v-else class="text-icon">⌕</span>
            {{ runLabel }}
          </button>
          <button v-if="appMode === 'expert'" class="ghost-btn compare-btn" :disabled="comparing || !question.trim()" @click="handleCompare">
            {{ comparing ? '对比中' : '策略对比' }}
          </button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <section v-if="appMode === 'expert' && compareResult" class="compare-panel">
          <div class="section-head">
            <div>
              <span class="section-kicker">Compare</span>
              <h3>检索策略对比</h3>
            </div>
            <span class="best-badge">Best：{{ compareResult.best_profile || '-' }}</span>
          </div>
          <div class="compare-grid">
            <article
              v-for="profile in compareResult.profiles"
              :key="profile.id"
              class="compare-card"
              :class="{ active: compareResult.best_profile === profile.id }"
            >
              <header>
                <strong>{{ profile.label }}</strong>
                <span>{{ profile.summary.returned }} 条</span>
              </header>
              <div class="score-meter">
                <span :style="{ width: `${Math.round(Math.min(1, profile.summary.top_score || 0) * 100)}%` }"></span>
              </div>
              <div class="trace-list compact">
                <span>Top：{{ profile.summary.top_source }}</span>
                <span>Score：{{ Number(profile.summary.top_score || 0).toFixed(4) }}</span>
                <span>Rewrite：{{ profile.trace.query_rewriter }}</span>
                <span>Rerank：{{ profile.trace.reranker }}</span>
              </div>
              <div v-if="profile.summary.matched_terms.length" class="term-row">
                <span v-for="term in profile.summary.matched_terms.slice(0, 6)" :key="term">{{ term }}</span>
              </div>
              <p v-if="profile.diagnostics.length" class="compare-diagnosis">
                {{ profile.diagnostics[0].title }}：{{ profile.diagnostics[0].action }}
              </p>
            </article>
          </div>
        </section>

        <section v-if="answer" class="answer-block">
          <div class="result-bar">
            <div>
              <span class="section-kicker">Result</span>
              <strong>
                {{ answer.citations.length }} 条证据 · confidence {{ confidenceLabel }}
                <template v-if="trust"> · {{ trust.label }}</template>
              </strong>
            </div>
            <button v-if="answer.answer" class="ghost-btn" @click="copyAnswer">{{ copied ? '已复制' : '复制回答' }}</button>
          </div>

          <div v-if="trust" class="trust-panel" :class="trust.level">
            <div class="trust-main">
              <div>
                <span class="section-kicker">Trust</span>
                <strong>{{ trust.label }}</strong>
                <p>{{ trust.reason }}</p>
              </div>
              <div class="trust-score" :style="{ '--coverage': percentLabel(citationAudit?.coverage) }">
                <span>{{ percentLabel(citationAudit?.coverage) }}</span>
                <small>引用覆盖率</small>
              </div>
            </div>
            <div class="trust-grid">
              <span>证据 {{ trust.evidence_count }}</span>
              <span>来源 {{ trust.source_count }}</span>
              <span>Top {{ trust.top_score }}</span>
              <span>Coverage {{ percentLabel(trust.coverage) }}</span>
            </div>
            <div v-if="trust.recommendations?.length" class="trust-notes">
              <span v-for="item in trust.recommendations" :key="item">{{ item }}</span>
            </div>
            <div v-if="citationAudit?.unsupported_claims?.length" class="unsupported-list">
              <strong>缺少直接引用的句子</strong>
              <p v-for="item in citationAudit.unsupported_claims.slice(0, 3)" :key="item">{{ item }}</p>
            </div>
          </div>

          <div v-if="answer.diagnostics?.length" class="diagnostic-list">
            <article v-for="item in answer.diagnostics" :key="`${item.level}-${item.title}`" class="diagnostic-card" :class="item.level">
              <strong>{{ item.title }}</strong>
              <span>{{ item.message }}</span>
              <small>{{ item.action }}</small>
              <div v-if="item.actions?.length" class="repair-actions">
                <button
                  v-for="action in item.actions"
                  :key="action.id"
                  class="ghost-btn"
                  :disabled="loading || rebuildingId === 'all'"
                  @click="handleDiagnosticAction(action)"
                >
                  {{ action.label }}
                </button>
              </div>
            </article>
          </div>

          <div v-if="workMode === 'answer'" class="answer-card">
            <pre>{{ answer.answer }}</pre>
          </div>

          <div v-if="workMode === 'answer'" class="action-panel">
            <div class="action-head">
              <strong>答案加工</strong>
              <button class="ghost-btn" :disabled="!answer.answer" @click="handleSaveCard">{{ cardMessage || '存为卡片' }}</button>
            </div>
            <div class="feedback-actions">
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('short')">更短</button>
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('detailed')">更详细</button>
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('interview')">面试回答</button>
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('resume')">简历 Bullet</button>
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('study')">学习笔记</button>
              <button class="ghost-btn" :disabled="rewriting" @click="handleRewrite('faq')">FAQ</button>
            </div>
            <div v-if="rewriteResult" class="rewrite-output">
              <strong>{{ rewriteResult.label }}</strong>
              <pre>{{ rewriteResult.rewritten }}</pre>
            </div>
          </div>

          <div v-if="workMode === 'answer'" class="feedback-panel">
            <input v-model="feedbackText" class="compact-input" type="text" placeholder="补充反馈，可选" />
            <div class="feedback-actions">
              <button class="ghost-btn" :disabled="feedbackSubmitting" @click="handleFeedback('up')">有帮助</button>
              <button class="ghost-btn" :disabled="feedbackSubmitting" @click="handleFeedback('down', 'bad_answer')">不准确</button>
              <button class="ghost-btn" :disabled="feedbackSubmitting" @click="handleFeedback('down', 'wrong_citation')">引用不对</button>
              <button class="ghost-btn" :disabled="feedbackSubmitting" @click="handleFeedback('down', 'retrieval_miss')">没搜到重点</button>
            </div>
            <span v-if="feedbackMessage">{{ feedbackMessage }}</span>
          </div>

          <div class="citations">
            <article
              v-for="(item, index) in answer.citations"
              :key="item.id"
              class="citation"
              :class="{ active: selectedCitation?.id === item.id }"
              @click="handleLoadContext(item)"
            >
              <div class="citation-rank">{{ index + 1 }}</div>
              <div class="citation-body">
                <header>
                  <strong>{{ item.filename }} · 片段 {{ item.index + 1 }}</strong>
                  <small v-if="item.page_number">第 {{ item.page_number }} 页</small>
                </header>
                <div class="score-meter">
                  <span :style="{ width: scoreWidth(item) }"></span>
                </div>
                <div class="evidence-strip">
                  <span>Evidence</span>
                  <strong>{{ item.rerank_score >= 0.35 ? '支持充分' : item.rerank_score >= 0.16 ? '需要核查' : '弱相关' }}</strong>
                  <small>{{ item.parent_context?.chunk_ids?.length || 1 }} context chunks</small>
                </div>
                <div class="score-row">
                  <span>rerank {{ item.rerank_score }}</span>
                  <span>base {{ item.score }}</span>
                  <span>bm25 {{ item.bm25_score }}</span>
                  <span>vector {{ item.vector_score }}</span>
                  <span v-if="item.cross_encoder_score !== null">cross {{ item.cross_encoder_score }}</span>
                </div>
                <div v-if="item.matched_terms.length" class="term-row">
                  <span v-for="term in item.matched_terms.slice(0, 8)" :key="term">{{ term }}</span>
                </div>
                <p>{{ item.snippet || shortText(item.text) }}</p>
              </div>
            </article>
            <p v-if="answer.citations.length === 0" class="empty-state">无匹配证据</p>
          </div>
        </section>

        <section v-else class="empty-state">
          <strong>Ready</strong>
          <span>{{ providerLabel }}</span>
        </section>
      </section>

      <aside class="panel inspector">
        <template v-if="appMode === 'user'">
          <div class="section-head">
            <div>
              <span class="section-kicker">Assistant</span>
              <h2>建议与资料</h2>
            </div>
            <button class="ghost-btn" @click="appMode = 'expert'; inspectorTab = 'trace'">查看过程</button>
          </div>

          <section class="debug-section flush">
            <h3>知识库健康</h3>
            <div v-if="overview" class="overview-card">
              <div class="status-grid compact-grid">
                <div>
                  <small>质量均分</small>
                  <strong>{{ avgQualityLabel }}</strong>
                </div>
                <div>
                  <small>待优化</small>
                  <strong>{{ overview.quality_distribution.needs_work }}</strong>
                </div>
              </div>
              <div v-if="overview.suggestions.length" class="trace-list">
                <span v-for="item in overview.suggestions.slice(0, 3)" :key="item">{{ item }}</span>
              </div>
            </div>
            <p v-else class="empty">等待知识库概览加载。</p>
          </section>

          <section class="debug-section">
            <h3>问题理解</h3>
            <div v-if="queryAnalysis" class="trace-list">
              <span>意图：{{ queryAnalysis.label }}</span>
              <span>建议：{{ queryAnalysis.recommended.search_profile }} / {{ queryAnalysis.recommended.search_mode }}</span>
              <span>{{ queryAnalysis.recommended.reason }}</span>
            </div>
            <p v-else class="empty">完成一次问答后，这里会显示问题意图和推荐检索策略。</p>
          </section>

          <section class="debug-section">
            <h3>资料缺口</h3>
            <div v-if="gapReport?.suggestions?.length" class="trace-list">
              <span v-for="item in gapReport.suggestions.slice(0, 4)" :key="item">{{ item }}</span>
            </div>
            <p v-else class="empty">系统会根据无答案、弱证据和反馈识别资料缺口。</p>
          </section>

          <section class="debug-section">
            <h3>知识卡片</h3>
            <div v-if="cards.length" class="related-list">
              <article v-for="item in cards.slice(0, 3)" :key="item.id">
                <strong>{{ item.title }}</strong>
                <span>{{ item.tags.slice(0, 4).join(' / ') || '未标记' }}</span>
                <p>{{ shortText(item.answer, 90) }}</p>
              </article>
            </div>
            <p v-else class="empty">好答案可以保存为卡片，用于复习和作品集沉淀。</p>
          </section>

          <section class="debug-section">
            <h3>系统建议</h3>
            <div v-if="diagnostics.length" class="side-suggestions">
              <article v-for="item in diagnostics" :key="`${item.level}-${item.title}`" class="diagnostic-card" :class="item.level">
                <strong>{{ item.title }}</strong>
                <span>{{ item.message }}</span>
                <div v-if="item.actions?.length" class="repair-actions">
                  <button
                    v-for="action in item.actions"
                    :key="action.id"
                    class="ghost-btn"
                    :disabled="loading || rebuildingId === 'all'"
                    @click="handleDiagnosticAction(action)"
                  >
                    {{ action.label }}
                  </button>
                </div>
              </article>
            </div>
            <p v-else class="empty">系统会在证据不足、范围过窄或模型降级时给出修复建议。</p>
          </section>

          <section class="debug-section">
            <h3>相关资料</h3>
            <div v-if="answer?.citations.length" class="related-list">
              <article v-for="item in answer.citations.slice(0, 4)" :key="item.id" @click="selectedCitation = item">
                <strong>{{ item.filename }}</strong>
                <span>片段 {{ item.index + 1 }} · score {{ item.rerank_score }}</span>
                <p>{{ item.snippet || shortText(item.text, 90) }}</p>
              </article>
            </div>
            <p v-else class="empty">完成一次问答后，这里会显示可追溯的相关资料。</p>
          </section>
        </template>

        <template v-else>
          <div class="inspector-tabs">
            <button :class="{ active: inspectorTab === 'trace' }" @click="inspectorTab = 'trace'">Trace</button>
            <button :class="{ active: inspectorTab === 'document' }" @click="inspectorTab = 'document'">Document</button>
          </div>

          <template v-if="inspectorTab === 'trace'">
          <div class="section-head">
            <div>
              <span class="section-kicker">Debug</span>
              <h2>检索链路</h2>
            </div>
          </div>

          <div class="status-grid">
            <div>
              <small>Retrieval</small>
              <strong>{{ providerLabel }}</strong>
            </div>
            <div>
              <small>Confidence</small>
              <strong>{{ confidenceLabel }}</strong>
            </div>
          </div>

          <template v-if="answer">
            <section class="debug-section">
              <h3>策略</h3>
              <div class="trace-list">
                <span>Mode：{{ answer.retrieval_trace.search_mode || searchMode }}</span>
                <span>Profile：{{ answer.retrieval_trace.search_profile || searchProfile }}</span>
                <span>Weights：BM25 {{ answer.retrieval_trace.bm25_weight }} / Vector {{ answer.retrieval_trace.vector_weight }}</span>
                <span>MMR：{{ answer.retrieval_trace.mmr_lambda }}</span>
                <span>Threshold：{{ answer.retrieval_trace.no_answer_threshold }}</span>
                <span>Rewrite Status：{{ answer.retrieval_trace.rewrite_status || '-' }}</span>
                <span>Vector Status：{{ answer.retrieval_trace.vector_status || '-' }}</span>
                <span>Rerank Status：{{ answer.retrieval_trace.rerank_status || '-' }}</span>
              </div>
            </section>

            <section v-if="answer.retrieval_trace.fallbacks?.length" class="debug-section">
              <h3>兜底事件</h3>
              <div class="trace-list">
                <span v-for="item in answer.retrieval_trace.fallbacks" :key="`${item.stage}-${item.action}`">
                  {{ item.stage }}：{{ item.action }}
                </span>
              </div>
            </section>

            <section v-if="answer.diagnostics?.length" class="debug-section">
              <h3>诊断建议</h3>
              <div class="trace-list">
                <span v-for="item in answer.diagnostics" :key="`${item.level}-${item.title}`">
                  {{ item.title }}：{{ item.action }}
                </span>
              </div>
            </section>

            <section class="debug-section">
              <h3>阶段</h3>
              <div class="trace-list">
                <span>Total：{{ answer.retrieval_trace.total_chunks }}</span>
                <span>Available：{{ answer.retrieval_trace.available_chunks ?? answer.retrieval_trace.total_chunks }}</span>
                <span>Raw：{{ answer.retrieval_trace.raw_candidates ?? '-' }}</span>
                <span>Deduped：{{ answer.retrieval_trace.deduped_candidates ?? '-' }}</span>
                <span>MMR：{{ answer.retrieval_trace.mmr_selected ?? '-' }}</span>
                <span>Returned：{{ answer.retrieval_trace.returned ?? answer.citations.length }}</span>
              </div>
            </section>

            <section class="debug-section">
              <h3>生成</h3>
              <div class="trace-list">
                <span>Provider：{{ answer.generation_trace.answer_provider || '-' }}</span>
                <span>Model：{{ answer.generation_trace.answer_model || '-' }}</span>
                <span>Grounded：{{ answer.generation_trace.grounded ? 'yes' : 'no' }}</span>
                <span>Rewrite：{{ answer.retrieval_trace.query_rewriter }}</span>
                <span>Rerank：{{ answer.retrieval_trace.reranker }}</span>
              </div>
            </section>

            <section v-if="citationAudit" class="debug-section">
              <h3>引用审计</h3>
              <div class="trace-list">
                <span>Coverage：{{ percentLabel(citationAudit.coverage) }}</span>
                <span>Sentences：{{ citationAudit.sentence_count }}</span>
                <span>Supported：{{ citationAudit.supported_sentence_count }}</span>
                <span>Unsupported：{{ citationAudit.unsupported_sentence_count }}</span>
              </div>
            </section>

            <section v-if="gapReport" class="debug-section">
              <h3>缺口分析</h3>
              <div class="trace-list">
                <span>Intent：{{ gapReport.query_intent.label }}</span>
                <span>Needs Action：{{ gapReport.needs_action ? 'yes' : 'no' }}</span>
                <span v-for="item in gapReport.suggestions.slice(0, 4)" :key="item">{{ item }}</span>
              </div>
            </section>

            <section v-if="metrics" class="debug-section">
              <h3>系统指标</h3>
              <div class="status-grid">
                <div>
                  <small>Avg Confidence</small>
                  <strong>{{ metrics.answering.avg_confidence }}</strong>
                </div>
                <div>
                  <small>Fallback</small>
                  <strong>{{ metrics.answering.fallback_count }}</strong>
                </div>
                <div>
                  <small>Negative</small>
                  <strong>{{ metrics.feedback.negative }}</strong>
                </div>
                <div>
                  <small>Low Quality</small>
                  <strong>{{ metrics.knowledge.low_quality_count }}</strong>
                </div>
              </div>
              <div class="trace-list metric-notes">
                <span v-for="item in metrics.recommendations.slice(0, 4)" :key="item">{{ item }}</span>
              </div>
            </section>

            <section v-if="evalDrafts.length" class="debug-section">
              <h3>评测草稿</h3>
              <div class="eval-form">
                <input v-model="evalQuestion" class="compact-input" type="text" placeholder="新增评测问题" />
                <input v-model="evalKeywords" class="compact-input" type="text" placeholder="期望关键词，用逗号分隔" />
                <div class="feedback-actions">
                  <button class="ghost-btn" :disabled="!evalQuestion.trim()" @click="handleCreateEvalCase">添加 Case</button>
                  <button class="ghost-btn" :disabled="evalRunning" @click="handleRunEvalDrafts">
                    {{ evalRunning ? '运行中' : '运行草稿' }}
                  </button>
                </div>
              </div>
              <div class="operation-list">
                <article v-for="item in evalDrafts.slice(0, 5)" :key="`${item.question}-${item.failure_type}`">
                  <strong>{{ item.failure_type }}</strong>
                  <span>{{ item.question }}</span>
                </article>
              </div>
              <div v-if="evalResults.length" class="operation-list eval-results">
                <article v-for="item in evalResults.slice(0, 5)" :key="item.question" :class="item.hit ? 'info' : 'warning'">
                  <strong>{{ item.hit ? 'hit' : 'miss' }}</strong>
                  <span>{{ item.question }}</span>
                </article>
              </div>
            </section>

            <section v-else class="debug-section">
              <h3>评测工作台</h3>
              <div class="eval-form">
                <input v-model="evalQuestion" class="compact-input" type="text" placeholder="新增评测问题" />
                <input v-model="evalKeywords" class="compact-input" type="text" placeholder="期望关键词，用逗号分隔" />
                <div class="feedback-actions">
                  <button class="ghost-btn" :disabled="!evalQuestion.trim()" @click="handleCreateEvalCase">添加 Case</button>
                  <button class="ghost-btn" :disabled="evalRunning" @click="handleRunEvalDrafts">
                    {{ evalRunning ? '运行中' : '运行草稿' }}
                  </button>
                </div>
              </div>
            </section>

            <section v-if="operations.length" class="debug-section">
              <h3>操作日志</h3>
              <div class="operation-list">
                <article v-for="item in operations.slice(0, 6)" :key="item.id" :class="item.level">
                  <strong>{{ item.event_type }}</strong>
                  <span>{{ item.message }}</span>
                </article>
              </div>
            </section>

            <section class="debug-section">
              <h3>查询</h3>
              <ol class="query-list">
                <li v-for="item in answer.retrieval_trace.rewritten_queries" :key="item">{{ item }}</li>
              </ol>
            </section>

            <section class="debug-section">
              <h3>当前证据</h3>
              <div v-if="selectedCitation" class="selected-citation">
                <strong>{{ selectedCitation.filename }} · 片段 {{ selectedCitation.index + 1 }}</strong>
                <div class="score-row">
                  <span>score {{ selectedCitation.score }}</span>
                  <span>rerank {{ selectedCitation.rerank_score }}</span>
                  <span>bm25 {{ selectedCitation.bm25_score }}</span>
                  <span>vector {{ selectedCitation.vector_score }}</span>
                </div>
                <div v-if="selectedCitation.matched_terms.length" class="term-row">
                  <span v-for="term in selectedCitation.matched_terms" :key="term">{{ term }}</span>
                </div>
                <p>{{ selectedCitation.text }}</p>
                <div v-if="citationContext" class="context-list">
                  <h4>上下文</h4>
                  <article v-for="ctx in citationContext.context" :key="ctx.id" :class="{ current: ctx.is_current }">
                    <strong>片段 {{ ctx.index + 1 }}</strong>
                    <p>{{ ctx.text }}</p>
                  </article>
                </div>
                <p v-else-if="loadingContext" class="empty">上下文加载中</p>
              </div>
              <p v-else class="empty">未选择证据</p>
            </section>
          </template>

          <section v-else class="debug-section">
            <h3>状态</h3>
            <p class="empty">等待检索</p>
          </section>
        </template>

          <template v-else>
          <div class="section-head">
            <div>
              <span class="section-kicker">Document</span>
              <h2>文档详情</h2>
            </div>
          </div>

          <section v-if="selectedDocument" class="debug-section flush">
            <div class="trace-list">
              <span>文件：{{ selectedDocument.document.filename }}</span>
              <span>类型：{{ selectedDocument.document.source_type }}</span>
              <span>页数：{{ selectedDocument.document.page_count }}</span>
              <span>Chunks：{{ selectedDocument.document.chunk_count }}</span>
              <span>Parser：{{ selectedDocument.document.metadata.parser || '-' }}</span>
              <span v-if="selectedDocument.document.metadata.ocr_status">OCR：{{ selectedDocument.document.metadata.ocr_status }}</span>
            </div>
            <div v-if="selectedDocument.document.quality" class="document-preview quality-preview">
              <h4>质量评分</h4>
              <div class="quality-head">
                <strong :class="['quality-score', qualityBadgeClass(selectedDocument.document.quality.score)]">
                  {{ selectedDocument.document.quality.score }}
                </strong>
                <span>{{ selectedDocument.document.quality.level }}</span>
              </div>
              <div class="trace-list">
                <span>平均 chunk {{ selectedDocument.document.quality.avg_chunk_length }}</span>
                <span>乱码率 {{ percentLabel(selectedDocument.document.quality.weird_char_ratio) }}</span>
                <span>重复率 {{ percentLabel(selectedDocument.document.quality.duplicate_chunk_ratio) }}</span>
              </div>
              <div v-if="selectedDocument.document.quality.suggestions.length" class="trust-notes">
                <span v-for="item in selectedDocument.document.quality.suggestions" :key="item">{{ item }}</span>
              </div>
            </div>
            <div v-if="selectedDocument.document.summary" class="document-preview">
              <h4>自动摘要</h4>
              <p>{{ selectedDocument.document.summary.one_sentence }}</p>
              <div v-if="selectedDocument.document.summary.key_concepts.length" class="term-row">
                <span v-for="term in selectedDocument.document.summary.key_concepts.slice(0, 8)" :key="term">{{ term }}</span>
              </div>
            </div>
            <div v-if="selectedDocument.document.lifecycle?.length" class="document-preview">
              <h4>索引生命周期</h4>
              <div class="timeline">
                <article v-for="item in selectedDocument.document.lifecycle" :key="`${item.stage}-${item.started_at}`">
                  <strong>{{ item.stage }}</strong>
                  <span>{{ item.status }} · {{ item.duration_ms }} ms</span>
                </article>
              </div>
            </div>
            <div class="document-preview">
              <h4>原文</h4>
              <p>{{ selectedDocument.document.pages[0]?.text || '无文本' }}</p>
            </div>
            <div class="document-preview">
              <h4>Chunks</h4>
              <article v-for="chunk in selectedDocument.chunks.slice(0, 8)" :key="chunk.id">
                <strong>片段 {{ chunk.index + 1 }}</strong>
                <p>{{ chunk.text }}</p>
              </article>
            </div>
          </section>

          <section v-else class="debug-section flush">
            <p class="empty">{{ loadingDocument ? '加载中' : '未选择文档' }}</p>
          </section>
          </template>
        </template>
      </aside>
    </section>
  </main>
</template>
