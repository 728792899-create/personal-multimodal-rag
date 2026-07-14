import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'

import {
  clearHistory,
  compareSearchStrategies,
  createEvalCase,
  deleteDocument,
  getChunkContext,
  getDocumentDetail,
  getKnowledgeOverview,
  getSystemMetrics,
  listDocuments,
  listEvalDrafts,
  listHistory,
  listKnowledgeCards,
  listOperations,
  rebuildAllDocuments,
  rebuildDocument,
  rewriteAnswer,
  runEvalDrafts,
  saveKnowledgeCard,
  searchDocuments,
  submitFeedback,
  ApiError,
  type AppMode,
  type AskResponse,
  type ChunkContext,
  type ChunkResult,
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
  type SearchMode,
  type SearchProfile,
  type SystemMetrics,
  type WorkMode,
  type ConversationStreamEvent,
} from '../api'
import { useConversations } from './useConversations'
import { useIngestionJobs } from './useIngestionJobs'
import { useKnowledgeBases } from './useKnowledgeBases'
import { useProviderStatus } from './useProviderStatus'


export function useWorkbench() {
  const knowledgeBaseState = useKnowledgeBases()
  const ingestionState = useIngestionJobs()
  const conversationState = useConversations()
  const providerState = useProviderStatus()
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
  const question = ref('如何优化 RAG 的召回质量？')
  const answer = ref<AskResponse | null>(null)
  const selectedCitation = ref<ChunkResult | null>(null)
  const citationContext = ref<ChunkContext | null>(null)
  const compareResult = ref<SearchCompareResponse | null>(null)
  const feedbackStats = ref<FeedbackStats | null>(null)
  const feedbackText = ref('')
  const feedbackMessage = ref('')
  const rewriteResult = ref<RewriteResponse | null>(null)
  const cardMessage = ref('')
  const evalQuestion = ref('')
  const evalKeywords = ref('')
  const evalResults = ref<EvaluationResult[]>([])

  const appMode = ref<AppMode>('user')
  const workMode = ref<WorkMode>('answer')
  const searchMode = ref<SearchMode>('hybrid')
  const searchProfile = ref<SearchProfile>('balanced')
  const topK = ref(5)
  const candidateK = ref(24)
  const vectorBalance = ref(0.38)
  const mmrLambda = ref(0.78)
  const minScore = ref(0.05)
  const queryRewrite = ref(true)
  const scopedDocumentIds = ref<string[]>([])
  const documentFilter = ref('')

  const booting = ref(true)
  const loading = ref(false)
  const uploading = ref(false)
  const importingUrl = ref(false)
  const comparing = ref(false)
  const rebuildingId = ref('')
  const loadingDocument = ref(false)
  const loadingContext = ref(false)
  const feedbackSubmitting = ref(false)
  const rewriting = ref(false)
  const evalRunning = ref(false)
  const error = ref('')
  const errorRequestId = ref('')
  const inspectorTab = ref<'trace' | 'citation' | 'document' | 'quality' | 'eval'>('trace')
  const lastRetry = shallowRef<null | (() => Promise<void>)>(null)

  let runController: AbortController | null = null
  let uploadController: AbortController | null = null
  let importController: AbortController | null = null

  const totalChunks = computed(() => documents.value.reduce((sum, item) => sum + item.chunk_count, 0))
  const totalChars = computed(() => documents.value.reduce((sum, item) => sum + item.char_count, 0))
  const avgQualityLabel = computed(() => overview.value ? Number(overview.value.avg_quality_score || 0).toFixed(1) : '—')
  const bm25Weight = computed(() => Number((1 - vectorBalance.value).toFixed(2)))
  const vectorWeight = computed(() => Number(vectorBalance.value.toFixed(2)))
  const scopeSet = computed(() => new Set(scopedDocumentIds.value))
  const scopeLabel = computed(() => {
    const base = knowledgeBaseState.selectedKnowledgeBase.value?.name || '默认知识库'
    return scopedDocumentIds.value.length ? `${base} · ${scopedDocumentIds.value.length} 份资料` : `${base} · 全部资料`
  })
  const filteredDocuments = computed(() => {
    const keyword = documentFilter.value.trim().toLowerCase()
    return keyword
      ? documents.value.filter((doc) => doc.filename.toLowerCase().includes(keyword) || doc.source_type.toLowerCase().includes(keyword))
      : documents.value
  })
  const isRefusal = computed(() => Boolean(answer.value?.retrieval_trace.refusal_reason))
  const diagnostics = computed(() => answer.value?.diagnostics ?? [])
  const citationAudit = computed(() => answer.value?.citation_audit)
  const trust = computed(() => answer.value?.trust)
  const streamAuditPending = computed(() => ['retrieving', 'streaming', 'auditing'].includes(conversationState.streamPhase.value))
  const expertParametersValid = computed(() => {
    if (appMode.value !== 'expert') return true
    return Number.isInteger(Number(topK.value))
      && Number(topK.value) >= 1
      && Number(topK.value) <= 12
      && Number.isInteger(Number(candidateK.value))
      && Number(candidateK.value) >= 1
      && Number(candidateK.value) <= 80
      && Number.isFinite(Number(minScore.value))
      && Number(minScore.value) >= 0
      && Number(minScore.value) <= 1
  })

  function clearError() {
    error.value = ''
    errorRequestId.value = ''
    lastRetry.value = null
  }

  function reportError(caught: unknown, fallback: string, retry?: () => Promise<void>) {
    if (caught instanceof DOMException && caught.name === 'AbortError') return
    const typed = caught as ApiError
    error.value = caught instanceof Error ? caught.message : fallback
    errorRequestId.value = typed?.requestId || ''
    lastRetry.value = retry || null
  }

  async function refreshDocuments() {
    const [nextDocuments, nextOverview] = await Promise.all([
      listDocuments({}, knowledgeBaseState.selectedKnowledgeBaseId.value),
      getKnowledgeOverview(),
    ])
    documents.value = nextDocuments
    overview.value = nextOverview
    const existing = new Set(nextDocuments.map((doc) => doc.id))
    scopedDocumentIds.value = scopedDocumentIds.value.filter((id) => existing.has(id))
  }

  async function refreshActivity() {
    const [nextHistory, nextOperations, nextCards, nextDrafts, nextMetrics] = await Promise.all([
      listHistory(),
      listOperations(20),
      listKnowledgeCards(20),
      listEvalDrafts(20),
      getSystemMetrics(),
    ])
    history.value = nextHistory
    operations.value = nextOperations
    cards.value = nextCards
    evalDrafts.value = nextDrafts
    metrics.value = nextMetrics
  }

  async function boot() {
    booting.value = true
    clearError()
    const knowledgeResult = await Promise.allSettled([knowledgeBaseState.refreshKnowledgeBases()])
    const results = await Promise.allSettled([
      refreshDocuments(),
      refreshActivity(),
      ingestionState.refreshIndexJobs(),
      conversationState.refreshConversations(),
      providerState.refreshProviderStatus(),
    ])
    results.push(...knowledgeResult)
    const failure = results.find((item) => item.status === 'rejected')
    if (failure?.status === 'rejected') reportError(failure.reason, '工作台初始化失败', boot)
    booting.value = false
  }

  function buildRetrievalOptions(): RetrievalOptions {
    if (appMode.value === 'user') {
      return {
        top_k: 5,
        candidate_k: 24,
        search_mode: 'hybrid',
        search_profile: 'balanced',
        document_ids: scopedDocumentIds.value,
        knowledge_base_ids: [knowledgeBaseState.selectedKnowledgeBaseId.value],
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
      knowledge_base_ids: [knowledgeBaseState.selectedKnowledgeBaseId.value],
      bm25_weight: bm25Weight.value,
      vector_weight: vectorWeight.value,
      mmr_lambda: mmrLambda.value,
      min_score: minScore.value,
      query_rewrite: queryRewrite.value,
      rerank_enabled: true,
    }
  }

  function searchOnlyAnswer(result: Awaited<ReturnType<typeof searchDocuments>>): AskResponse {
    const confidence = result.results[0]?.rerank_score ?? result.results[0]?.score ?? 0
    return {
      answer: '',
      citations: result.results,
      retrieval_trace: result.trace,
      generation_trace: { answer_provider: 'search-only', grounded: true, skipped: true, citation_count: result.results.length },
      confidence,
      diagnostics: result.diagnostics,
      trust: {
        level: result.results.length ? 'medium' : 'unknown',
        label: result.results.length ? '证据列表' : '无法确定',
        reason: result.results.length ? '只检索模式，请人工核验证据。' : '未检索到证据。',
        evidence_count: result.results.length,
        source_count: new Set(result.results.map((item) => item.document_id)).size,
        top_score: confidence,
        confidence,
        coverage: 0,
        recommendations: ['只检索模式不会生成答案。'],
      },
      citation_audit: {
        coverage: 0, sentence_count: 0, supported_sentence_count: 0,
        unsupported_sentence_count: 0, unsupported_claims: [], checked: true,
      },
    }
  }

  async function handleRun() {
    if (!question.value.trim()) return
    if (!expertParametersValid.value) {
      reportError(new ApiError('请先修复专家检索参数，再运行查询。'), '检索参数无效')
      return
    }
    runController?.abort()
    runController = new AbortController()
    loading.value = true
    clearError()
    feedbackMessage.value = ''
    rewriteResult.value = null
    cardMessage.value = ''
    citationContext.value = null
    compareResult.value = null
    try {
      const options = buildRetrievalOptions()
      if (workMode.value === 'answer') {
        answer.value = await conversationState.askInConversation(
          question.value.trim(),
          [knowledgeBaseState.selectedKnowledgeBaseId.value],
          options,
          (event: ConversationStreamEvent, partialText: string) => {
            if (event.type === 'retrieval.completed' && event.retrieval_trace) {
              answer.value = {
                answer: '',
                citations: event.citations || [],
                retrieval_trace: event.retrieval_trace,
                generation_trace: {},
                confidence: event.confidence ?? 0,
                diagnostics: event.diagnostics || [],
              }
            } else if (event.type === 'answer.delta' && answer.value) {
              answer.value = { ...answer.value, answer: partialText }
            } else if (event.type === 'answer.completed' || event.type === 'refusal') {
              answer.value = event.response
            }
          },
        )
      } else {
        answer.value = searchOnlyAnswer(await searchDocuments(question.value.trim(), options, { signal: runController.signal }))
      }
      selectedCitation.value = answer.value.citations[0] ?? null
      inspectorTab.value = 'trace'
      await refreshActivity()
    } catch (caught) {
      reportError(caught, '检索请求失败', handleRun)
    } finally {
      loading.value = false
      runController = null
    }
  }

  function cancelRun() {
    runController?.abort()
    conversationState.cancelStream()
    loading.value = false
  }

  async function handleUpload() {
    if (!selectedFile.value) return
    uploadController?.abort()
    uploadController = new AbortController()
    uploading.value = true
    clearError()
    try {
      await ingestionState.ingestFile(
        selectedFile.value,
        knowledgeBaseState.selectedKnowledgeBaseId.value,
        uploadController.signal,
      )
      selectedFile.value = null
      await Promise.all([refreshDocuments(), refreshActivity()])
    } catch (caught) {
      reportError(caught, '上传失败', handleUpload)
    } finally {
      uploading.value = false
      uploadController = null
    }
  }

  async function handleImportUrl() {
    if (!urlToImport.value.trim()) return
    importController?.abort()
    importController = new AbortController()
    importingUrl.value = true
    clearError()
    try {
      await ingestionState.ingestUrl(
        urlToImport.value.trim(),
        knowledgeBaseState.selectedKnowledgeBaseId.value,
        importController.signal,
      )
      urlToImport.value = ''
      await Promise.all([refreshDocuments(), refreshActivity()])
    } catch (caught) {
      reportError(caught, 'URL 导入失败', handleImportUrl)
    } finally {
      importingUrl.value = false
      importController = null
    }
  }

  async function handleCompare() {
    if (!question.value.trim()) return
    if (!expertParametersValid.value) {
      reportError(new ApiError('请先修复专家检索参数，再运行策略对比。'), '检索参数无效')
      return
    }
    comparing.value = true
    clearError()
    try {
      compareResult.value = await compareSearchStrategies(question.value.trim(), buildRetrievalOptions())
    } catch (caught) {
      reportError(caught, '检索策略对比失败', handleCompare)
    } finally {
      comparing.value = false
    }
  }

  async function selectCitation(item: ChunkResult) {
    selectedCitation.value = item
    citationContext.value = null
    inspectorTab.value = 'citation'
    loadingContext.value = true
    try {
      citationContext.value = await getChunkContext(item.id, 1)
    } catch (caught) {
      reportError(caught, '引用上下文加载失败', () => selectCitation(item))
    } finally {
      loadingContext.value = false
    }
  }

  async function selectDocument(documentId: string) {
    loadingDocument.value = true
    clearError()
    try {
      selectedDocument.value = await getDocumentDetail(documentId)
      inspectorTab.value = 'document'
    } catch (caught) {
      reportError(caught, '文档详情加载失败', () => selectDocument(documentId))
    } finally {
      loadingDocument.value = false
    }
  }

  async function removeDocument(documentId: string) {
    if (!window.confirm('确认删除这份文档及其索引吗？')) return
    clearError()
    try {
      await deleteDocument(documentId)
      if (selectedDocument.value?.document.id === documentId) selectedDocument.value = null
      if (selectedCitation.value?.document_id === documentId) selectedCitation.value = null
      await Promise.all([refreshDocuments(), refreshActivity()])
    } catch (caught) {
      reportError(caught, '删除失败', () => removeDocument(documentId))
    }
  }

  async function rebuildOne(documentId: string) {
    rebuildingId.value = documentId
    clearError()
    try {
      await rebuildDocument(documentId)
      await refreshDocuments()
      await selectDocument(documentId)
    } catch (caught) {
      reportError(caught, '重建索引失败', () => rebuildOne(documentId))
    } finally {
      rebuildingId.value = ''
    }
  }

  async function rebuildAll() {
    if (!window.confirm('确认重建全部文档索引吗？')) return
    rebuildingId.value = 'all'
    clearError()
    try {
      await rebuildAllDocuments()
      await Promise.all([refreshDocuments(), refreshActivity()])
    } catch (caught) {
      reportError(caught, '重建全部索引失败', rebuildAll)
    } finally {
      rebuildingId.value = ''
    }
  }

  function toggleScope(documentId: string) {
    scopedDocumentIds.value = scopeSet.value.has(documentId)
      ? scopedDocumentIds.value.filter((id) => id !== documentId)
      : [...scopedDocumentIds.value, documentId]
  }

  function clearScope() {
    scopedDocumentIds.value = []
  }

  async function selectKnowledgeBase(knowledgeBaseId: string) {
    if (knowledgeBaseId === knowledgeBaseState.selectedKnowledgeBaseId.value) return
    knowledgeBaseState.selectedKnowledgeBaseId.value = knowledgeBaseId
    scopedDocumentIds.value = []
    selectedDocument.value = null
    answer.value = null
    await refreshDocuments()
  }

  async function addKnowledgeBase() {
    try {
      const created = await knowledgeBaseState.addKnowledgeBase()
      if (created) {
        knowledgeBaseState.selectedKnowledgeBaseId.value = created.id
        scopedDocumentIds.value = []
        answer.value = null
        await refreshDocuments()
      }
    } catch (caught) {
      reportError(caught, '创建知识库失败', addKnowledgeBase)
    }
  }

  async function startNewConversation() {
    conversationState.activeConversationId.value = ''
    conversationState.conversationMessages.value = []
    answer.value = null
  }

  async function openConversation(conversationId: string) {
    try {
      await conversationState.selectConversation(conversationId)
      const assistant = [...conversationState.conversationMessages.value]
        .reverse()
        .find((item) => item.role === 'assistant' && item.status === 'completed')
      const storedResponse = assistant?.metadata?.response
      if (storedResponse && typeof storedResponse === 'object') {
        answer.value = storedResponse as AskResponse
        selectedCitation.value = answer.value.citations[0] ?? null
      }
    } catch (caught) {
      reportError(caught, '会话加载失败', () => openConversation(conversationId))
    }
  }

  function useHistory(item: HistoryItem) {
    appMode.value = 'user'
    workMode.value = 'answer'
    question.value = item.question
    answer.value = item
    selectedCitation.value = item.citations[0] ?? null
    inspectorTab.value = 'trace'
  }

  async function eraseHistory() {
    if (!window.confirm('确认清空全部问答历史吗？')) return
    await clearHistory()
    history.value = []
  }

  async function handleFeedback(rating: 'up' | 'down') {
    if (!answer.value) return
    feedbackSubmitting.value = true
    clearError()
    try {
      const result = await submitFeedback({
        history_id: answer.value.history_id,
        question: question.value,
        answer: answer.value.answer,
        rating,
        feedback_text: feedbackText.value,
        failure_type: rating === 'down' ? 'bad_answer' : undefined,
        citations: answer.value.citations,
      })
      feedbackStats.value = result.stats
      feedbackMessage.value = rating === 'up' ? '已记录为有效回答' : '已生成评测草稿'
      feedbackText.value = ''
      await refreshActivity()
    } catch (caught) {
      reportError(caught, '反馈提交失败', () => handleFeedback(rating))
    } finally {
      feedbackSubmitting.value = false
    }
  }

  async function handleRewrite(style: RewriteStyle) {
    if (!answer.value?.answer) return
    rewriting.value = true
    clearError()
    try {
      rewriteResult.value = await rewriteAnswer(question.value, answer.value.answer, style, answer.value.citations)
    } catch (caught) {
      reportError(caught, '答案改写失败', () => handleRewrite(style))
    } finally {
      rewriting.value = false
    }
  }

  async function handleSaveCard() {
    if (!answer.value?.answer) return
    clearError()
    try {
      await saveKnowledgeCard(question.value, answer.value.answer, answer.value.citations)
      cardMessage.value = '已保存知识卡片'
      await refreshActivity()
    } catch (caught) {
      reportError(caught, '保存知识卡片失败', handleSaveCard)
    }
  }

  async function handleCreateEvalCase() {
    if (!evalQuestion.value.trim()) return
    const keywords = evalKeywords.value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean)
    try {
      await createEvalCase(evalQuestion.value.trim(), keywords)
      evalQuestion.value = ''
      evalKeywords.value = ''
      await refreshActivity()
    } catch (caught) {
      reportError(caught, '创建评测 case 失败', handleCreateEvalCase)
    }
  }

  async function handleRunEvalDrafts() {
    evalRunning.value = true
    try {
      const result = await runEvalDrafts(50)
      evalResults.value = result.results
      await refreshActivity()
    } catch (caught) {
      reportError(caught, '运行评测失败', handleRunEvalDrafts)
    } finally {
      evalRunning.value = false
    }
  }

  async function handleDiagnosticAction(action: DiagnosticAction) {
    const payload = action.payload || {}
    if (action.id === 'open_expert_trace') {
      appMode.value = 'expert'
      inspectorTab.value = 'trace'
      return
    }
    if (action.id === 'view_evidence_only') workMode.value = 'search'
    if (action.id === 'rebuild_all_indexes') return rebuildAll()
    if (Array.isArray(payload.document_ids)) scopedDocumentIds.value = payload.document_ids as string[]
    if (typeof payload.min_score === 'number') minScore.value = payload.min_score
    if (typeof payload.candidate_k_multiplier === 'number') candidateK.value = Math.min(80, Math.max(12, candidateK.value * payload.candidate_k_multiplier))
    if (['hybrid', 'keyword', 'semantic'].includes(String(payload.search_mode))) searchMode.value = payload.search_mode as SearchMode
    if (['balanced', 'precision', 'recall'].includes(String(payload.search_profile))) searchProfile.value = payload.search_profile as SearchProfile
    appMode.value = 'expert'
    await handleRun()
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

  async function retryLast() {
    const retry = lastRetry.value
    clearError()
    await retry?.()
  }

  onBeforeUnmount(() => {
    runController?.abort()
    uploadController?.abort()
    importController?.abort()
    conversationState.cancelStream()
  })

  return {
    documents, history, overview, operations, cards, evalDrafts, metrics,
    selectedDocument, selectedFile, urlToImport, question, answer, selectedCitation,
    citationContext, compareResult, feedbackStats, feedbackText, feedbackMessage,
    rewriteResult, cardMessage, evalQuestion, evalKeywords, evalResults,
    appMode, workMode, searchMode, searchProfile, topK, candidateK, vectorBalance,
    mmrLambda, minScore, queryRewrite, scopedDocumentIds, documentFilter, inspectorTab,
    booting, loading, uploading, importingUrl, comparing, rebuildingId, loadingDocument,
    loadingContext, feedbackSubmitting, rewriting, evalRunning, error, errorRequestId,
    totalChunks, totalChars, avgQualityLabel, bm25Weight, vectorWeight, scopeSet,
    scopeLabel, filteredDocuments, isRefusal, diagnostics, citationAudit, trust,
    expertParametersValid,
    boot, handleRun, cancelRun, handleUpload, handleImportUrl, handleCompare,
    selectCitation, selectDocument, removeDocument, rebuildOne, rebuildAll,
    toggleScope, clearScope, useHistory, eraseHistory, handleFeedback, handleRewrite,
    handleSaveCard, handleCreateEvalCase, handleRunEvalDrafts, handleDiagnosticAction,
    resetRetrievalControls, retryLast, clearError,
    knowledgeBases: knowledgeBaseState.knowledgeBases,
    selectedKnowledgeBaseId: knowledgeBaseState.selectedKnowledgeBaseId,
    selectedKnowledgeBase: knowledgeBaseState.selectedKnowledgeBase,
    loadingKnowledgeBases: knowledgeBaseState.loadingKnowledgeBases,
    newKnowledgeBaseName: knowledgeBaseState.newKnowledgeBaseName,
    indexJobs: ingestionState.indexJobs,
    activeJobs: ingestionState.activeJobs,
    cancelIndexJob: ingestionState.cancelJob,
    retryIndexJob: ingestionState.retryJob,
    conversations: conversationState.conversations,
    conversationMessages: conversationState.conversationMessages,
    activeConversationId: conversationState.activeConversationId,
    streamPhase: conversationState.streamPhase,
    streamAuditPending,
    providerStatus: providerState.providerStatus,
    selectKnowledgeBase,
    addKnowledgeBase,
    startNewConversation,
    selectConversation: openConversation,
    removeConversation: conversationState.removeConversation,
  }
}

export type Workbench = ReturnType<typeof useWorkbench>
