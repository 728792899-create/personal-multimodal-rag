import { computed, onBeforeUnmount, ref, shallowRef, unref, type MaybeRef } from 'vue'

import {
  clearHistory,
  compareSearchStrategies,
  createEvalCase,
  deleteDocument,
  getChunkContext,
  getEvalReviewSummary,
  getRealUsageSummary,
  getKnowledgeOverview,
  getSystemMetrics,
  listDocuments,
  listEvalDrafts,
  listHistory,
  listKnowledgeCards,
  listOperations,
  rebuildAllDocuments,
  rebuildDocument,
  reviewEvalCase,
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
  type DocumentElementType,
  type DocumentMeta,
  type EvalDraft,
  type EvalReviewSummary,
  type EvaluationResult,
  type FeedbackStats,
  type HistoryItem,
  type KnowledgeCard,
  type KnowledgeOverview,
  type OperationLog,
  type RetrievalOptions,
  type RealUsageSummary,
  type RewriteResponse,
  type RewriteStyle,
  type SearchCompareResponse,
  type SearchMode,
  type SearchProfile,
  type RetrievalStrategy,
  type RoutingMode,
  type SystemMetrics,
  type WorkMode,
  type ConversationStreamEvent,
} from '../api'
import { localizedSystemText } from '../localization'
import { useConversations } from './useConversations'
import { useIngestionJobs } from './useIngestionJobs'
import { useKnowledgeBases } from './useKnowledgeBases'
import { useProviderStatus } from './useProviderStatus'
import { useDocumentViewer } from './useDocumentViewer'
import { useGraphTrace } from './useGraphTrace'
import { useMultimodalQuery } from './useMultimodalQuery'
import { useQualityAudit } from './useQualityAudit'


type WorkbenchRole = 'admin' | 'editor' | 'viewer' | 'owner' | ''


export function useWorkbench(role: MaybeRef<WorkbenchRole> = 'admin') {
  const currentRole = computed(() => unref(role) || 'viewer')
  const canAdmin = computed(() => ['admin', 'owner'].includes(currentRole.value))
  const canEdit = computed(() => canAdmin.value || currentRole.value === 'editor')
  const knowledgeBaseState = useKnowledgeBases()
  const ingestionState = useIngestionJobs()
  const conversationState = useConversations()
  const providerState = useProviderStatus()
  const documentViewer = useDocumentViewer()
  const graphState = useGraphTrace()
  const multimodalQuery = useMultimodalQuery()
  const documents = ref<DocumentMeta[]>([])
  const history = ref<HistoryItem[]>([])
  const overview = ref<KnowledgeOverview | null>(null)
  const operations = ref<OperationLog[]>([])
  const cards = ref<KnowledgeCard[]>([])
  const evalDrafts = ref<EvalDraft[]>([])
  const metrics = ref<SystemMetrics | null>(null)
  const selectedDocument = documentViewer.document
  const selectedFile = ref<File | null>(null)
  const urlToImport = ref('')
  const question = ref('')
  const answer = ref<AskResponse | null>(null)
  const qualityAudit = useQualityAudit(answer)
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
  const evalReviewSummary = ref<EvalReviewSummary | null>(null)
  const evalReviewerId = ref('')
  const evalReviewingId = ref('')
  const evalReviewMessage = ref('')
  const realUsageConsent = ref(false)
  const realUsageSummary = ref<RealUsageSummary | null>(null)

  const appMode = ref<AppMode>('user')
  const workMode = ref<WorkMode>('answer')
  const searchMode = ref<SearchMode>('hybrid')
  const searchProfile = ref<SearchProfile>('balanced')
  const retrievalStrategy = ref<RetrievalStrategy>('auto')
  const routingMode = ref<RoutingMode>('auto')
  const graphWeight = ref(0.25)
  const graphMaxHops = ref(2)
  const parentWindow = ref(1)
  const modalityFilters = ref<DocumentElementType[]>([])
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
  const loadingDocument = documentViewer.loading
  const loadingContext = ref(false)
  const feedbackSubmitting = ref(false)
  const rewriting = ref(false)
  const evalRunning = ref(false)
  const error = ref('')
  const errorCode = ref('')
  const errorRequestId = ref('')
  const inspectorTab = ref<'trace' | 'graph' | 'citation' | 'document' | 'quality' | 'eval'>('trace')
  const lastRetry = shallowRef<null | (() => Promise<void>)>(null)

  let runController: AbortController | null = null
  let uploadController: AbortController | null = null
  let importController: AbortController | null = null
  let runGeneration = 0

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
  const isRefusal = qualityAudit.isRefusal
  const diagnostics = qualityAudit.diagnostics
  const citationAudit = qualityAudit.citationAudit
  const trust = qualityAudit.trust
  const streamAuditPending = computed(() => ['enriching', 'retrieving', 'streaming', 'auditing'].includes(conversationState.streamPhase.value))
  const answerFinalized = computed(() => {
    if (!answer.value) return false
    if (workMode.value === 'search') return !loading.value
    return conversationState.streamPhase.value === 'completed'
  })
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
      && Number(graphWeight.value) >= 0
      && Number(graphWeight.value) <= 1
      && Number.isInteger(Number(graphMaxHops.value))
      && Number(graphMaxHops.value) >= 1
      && Number(graphMaxHops.value) <= 4
  })

  function clearError() {
    error.value = ''
    errorCode.value = ''
    errorRequestId.value = ''
    lastRetry.value = null
  }

  function reportError(caught: unknown, fallback: string, retry?: () => Promise<void>) {
    if (caught instanceof DOMException && caught.name === 'AbortError') return
    const typed = caught as ApiError
    error.value = localizedSystemText(caught instanceof Error ? caught.message : '', fallback)
    errorCode.value = typed?.code || ''
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
    const tasks: Promise<void>[] = [
      listKnowledgeCards(20).then((items) => { cards.value = items }),
    ]
    if (canEdit.value) {
      tasks.push(
        listEvalDrafts(220).then((items) => { evalDrafts.value = items }),
        getEvalReviewSummary().then((summary) => { evalReviewSummary.value = summary }),
      )
    } else {
      evalDrafts.value = []
      evalReviewSummary.value = null
    }
    if (canAdmin.value) {
      tasks.push(
        listHistory().then((items) => { history.value = items }),
        listOperations(20).then((items) => { operations.value = items }),
        getSystemMetrics().then((nextMetrics) => { metrics.value = nextMetrics }),
        getRealUsageSummary().then((summary) => { realUsageSummary.value = summary }),
      )
    } else {
      history.value = []
      operations.value = []
      metrics.value = null
      realUsageSummary.value = null
    }
    await Promise.all(tasks)
  }

  async function boot() {
    booting.value = true
    clearError()
    const knowledgeResult = await Promise.allSettled([knowledgeBaseState.refreshKnowledgeBases()])
    const startupTasks = [
      refreshDocuments(),
      refreshActivity(),
      conversationState.refreshConversations(),
      providerState.refreshProviderStatus(),
      graphState.load(knowledgeBaseState.selectedKnowledgeBaseId.value),
    ]
    if (canAdmin.value) startupTasks.push(ingestionState.refreshIndexJobs())
    else ingestionState.indexJobs.value = []
    const results = await Promise.allSettled(startupTasks)
    results.push(...knowledgeResult)
    if (results[2]?.status === 'fulfilled') {
      try {
        if (await conversationState.restoreActiveConversation()) {
          await alignKnowledgeBaseWithActiveConversation()
          hydrateConversation()
        }
      } catch (caught) {
        results.push({ status: 'rejected', reason: caught })
      }
    }
    const failure = results.find((item) => item.status === 'rejected')
    if (failure?.status === 'rejected') reportError(failure.reason, '工作台初始化失败', boot)
    booting.value = false
  }

  function buildRetrievalOptions(): RetrievalOptions {
    if (appMode.value === 'user') {
      return {
        routing_mode: 'auto',
        top_k: 5,
        candidate_k: 24,
        search_mode: 'hybrid',
        search_profile: 'balanced',
        strategy: 'auto',
        document_ids: scopedDocumentIds.value,
        knowledge_base_ids: [knowledgeBaseState.selectedKnowledgeBaseId.value],
        bm25_weight: 0.62,
        vector_weight: 0.38,
        mmr_lambda: 0.78,
        min_score: 0.05,
        query_rewrite: true,
        rerank_enabled: true,
        graph_weight: 0.25,
        graph_max_hops: 2,
        parent_window: 1,
      }
    }
    return {
      routing_mode: routingMode.value,
      top_k: topK.value,
      candidate_k: candidateK.value,
      search_mode: searchMode.value,
      search_profile: searchProfile.value,
      strategy: retrievalStrategy.value,
      document_ids: scopedDocumentIds.value,
      knowledge_base_ids: [knowledgeBaseState.selectedKnowledgeBaseId.value],
      bm25_weight: bm25Weight.value,
      vector_weight: vectorWeight.value,
      mmr_lambda: mmrLambda.value,
      min_score: minScore.value,
      query_rewrite: queryRewrite.value,
      rerank_enabled: true,
      graph_weight: graphWeight.value,
      graph_max_hops: graphMaxHops.value,
      modality_filters: modalityFilters.value,
      parent_window: parentWindow.value,
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
    if (booting.value || loading.value) return
    if (!question.value.trim()) return
    if (workMode.value === 'search' && multimodalQuery.attachments.value.length) {
      reportError(new ApiError('图片提问需使用“问答”模式以完成查询增强与最终审计。'), '当前模式不支持附件')
      return
    }
    if (!expertParametersValid.value) {
      reportError(new ApiError('请先修复专家检索参数，再运行查询。'), '检索参数无效')
      return
    }
    const generation = ++runGeneration
    const requestController = new AbortController()
    runController = requestController
    loading.value = true
    clearError()
    answer.value = null
    selectedCitation.value = null
    feedbackMessage.value = ''
    rewriteResult.value = null
    cardMessage.value = ''
    citationContext.value = null
    compareResult.value = null
    try {
      const options = buildRetrievalOptions()
      if (workMode.value === 'answer') {
        const nextAnswer = await conversationState.askInConversation(
          question.value.trim(),
          [knowledgeBaseState.selectedKnowledgeBaseId.value],
          options,
          multimodalQuery.attachmentRefs.value,
          realUsageConsent.value,
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
            } else if (event.type === 'error' && event.response) {
              answer.value = event.response
            }
          },
        )
        if (generation !== runGeneration) return
        answer.value = nextAnswer
      } else {
        const nextAnswer = searchOnlyAnswer(await searchDocuments(
          question.value.trim(),
          options,
          { signal: requestController.signal },
        ))
        if (generation !== runGeneration) return
        answer.value = nextAnswer
      }
      selectedCitation.value = answer.value.citations[0] ?? null
      inspectorTab.value = 'trace'
      await refreshActivity()
    } catch (caught) {
      if (generation === runGeneration) {
        reportError(
          caught,
          answer.value?.citations.length
            ? '回答生成未完成，已保留检索证据，请重试。'
            : '查询请求失败，请重试。',
          handleRun,
        )
      }
    } finally {
      if (generation === runGeneration) loading.value = false
      if (runController === requestController) runController = null
    }
  }

  function cancelRun() {
    runGeneration += 1
    const current = runController
    runController = null
    current?.abort()
    conversationState.cancelStream()
    loading.value = false
  }

  async function handleUpload() {
    if (!canEdit.value) return
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
    if (!canEdit.value) return
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

  async function selectDocument(documentId: string): Promise<boolean> {
    clearError()
    try {
      await documentViewer.open(documentId)
      inspectorTab.value = 'document'
      return true
    } catch (caught) {
      reportError(caught, '文档详情加载失败', async () => {
        await selectDocument(documentId)
      })
      return false
    }
  }

  async function openCitationElement() {
    const citation = selectedCitation.value
    const elementId = citation?.element_ids?.[0]
    if (!citation || !elementId) return
    clearError()
    try {
      await documentViewer.open(citation.document_id, elementId)
      inspectorTab.value = 'document'
    } catch (caught) {
      reportError(caught, '无法定位引用元素', openCitationElement)
    }
  }

  async function removeDocument(documentId: string) {
    if (!canEdit.value) return
    if (!window.confirm('确认删除这份文档及其索引吗？')) return
    clearError()
    try {
      await deleteDocument(documentId)
      if (selectedDocument.value?.document.id === documentId) documentViewer.clear()
      if (selectedCitation.value?.document_id === documentId) selectedCitation.value = null
      await Promise.all([refreshDocuments(), refreshActivity()])
    } catch (caught) {
      reportError(caught, '删除失败', () => removeDocument(documentId))
    }
  }

  async function rebuildOne(documentId: string) {
    if (!canAdmin.value) return
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
    if (!canAdmin.value) return
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
    if (loading.value) cancelRun()
    knowledgeBaseState.selectedKnowledgeBaseId.value = knowledgeBaseId
    scopedDocumentIds.value = []
    documentViewer.clear()
    answer.value = null
    await multimodalQuery.clear()
    await Promise.all([refreshDocuments(), graphState.load(knowledgeBaseId)])
  }

  async function addKnowledgeBase() {
    if (!canEdit.value) return
    try {
      const created = await knowledgeBaseState.addKnowledgeBase()
      if (created) {
        knowledgeBaseState.selectedKnowledgeBaseId.value = created.id
        scopedDocumentIds.value = []
        answer.value = null
        await Promise.all([refreshDocuments(), graphState.load(created.id)])
      }
    } catch (caught) {
      reportError(caught, '创建知识库失败', addKnowledgeBase)
    }
  }

  async function startNewConversation() {
    cancelRun()
    conversationState.clearActiveConversation()
    question.value = ''
    answer.value = null
    selectedCitation.value = null
    citationContext.value = null
    compareResult.value = null
    feedbackText.value = ''
    feedbackMessage.value = ''
    rewriteResult.value = null
    cardMessage.value = ''
    realUsageConsent.value = false
    inspectorTab.value = 'trace'
    clearError()
    await multimodalQuery.clear()
  }

  async function openConversation(conversationId: string) {
    if (loading.value) cancelRun()
    clearError()
    try {
      await conversationState.selectConversation(conversationId)
      await alignKnowledgeBaseWithActiveConversation()
      hydrateConversation()
    } catch (caught) {
      reportError(caught, '会话加载失败', () => openConversation(conversationId))
    }
  }

  async function alignKnowledgeBaseWithActiveConversation() {
    const active = conversationState.conversations.value.find(
      (item) => item.id === conversationState.activeConversationId.value,
    )
    const knowledgeBaseId = active?.knowledge_base_ids[0]
    if (
      !knowledgeBaseId
      || knowledgeBaseId === knowledgeBaseState.selectedKnowledgeBaseId.value
      || !knowledgeBaseState.knowledgeBases.value.some((item) => item.id === knowledgeBaseId)
    ) return
    knowledgeBaseState.selectedKnowledgeBaseId.value = knowledgeBaseId
    scopedDocumentIds.value = []
    documentViewer.clear()
    await Promise.all([refreshDocuments(), graphState.load(knowledgeBaseId)])
  }

  function hydrateConversation() {
    const messages = conversationState.conversationMessages.value
    let latestUserIndex = -1
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') {
        latestUserIndex = index
        break
      }
    }
    const user = latestUserIndex >= 0 ? messages[latestUserIndex] : undefined
    const assistant = latestUserIndex >= 0
      ? messages.slice(latestUserIndex + 1).find((item) => item.role === 'assistant')
      : undefined
    const storedResponse = assistant?.metadata?.response
    question.value = user?.content || ''
    answer.value = storedResponse && typeof storedResponse === 'object'
      ? storedResponse as AskResponse
      : null
    selectedCitation.value = answer.value?.citations[0] ?? null
    citationContext.value = null
    compareResult.value = null
    workMode.value = 'answer'
    inspectorTab.value = 'trace'
    if (assistant?.status === 'failed') {
      error.value = '上次回答生成未完成，请重试。'
      errorCode.value = 'PREVIOUS_ANSWER_FAILED'
      lastRetry.value = handleRun
    } else if (assistant?.status === 'cancelled' || assistant?.status === 'streaming') {
      error.value = '上次回答已中断，可以重新发送问题。'
      errorCode.value = 'PREVIOUS_ANSWER_INTERRUPTED'
      lastRetry.value = handleRun
    }
  }

  function useHistory(item: HistoryItem) {
    appMode.value = 'user'
    workMode.value = 'answer'
    conversationState.streamPhase.value = 'completed'
    question.value = item.question
    answer.value = item
    selectedCitation.value = item.citations[0] ?? null
    inspectorTab.value = 'trace'
  }

  async function eraseHistory() {
    if (!canAdmin.value) return
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
    if (!canEdit.value) return
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
    if (!canEdit.value) return
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
    if (!canEdit.value) return
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
    if (!canEdit.value) return
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

  async function handleReviewEvalCase(item: EvalDraft) {
    if (!canAdmin.value) return
    if (!item.id || !evalReviewerId.value.trim()) return
    evalReviewingId.value = item.id
    evalReviewMessage.value = ''
    const expectedKeywords = Array.isArray(item.expected_keywords)
      ? item.expected_keywords.filter(Boolean)
      : []
    try {
      const result = await reviewEvalCase(item.id, {
        expected_answer: item.expected_answer || '',
        expected_keywords: expectedKeywords,
        expected_document_ids: item.expected_document_ids || [],
        answerable: item.answerable !== false,
        note: item.note || '',
        reviewer_id: evalReviewerId.value.trim(),
        reviewer_attestation: 'human-reviewed',
      })
      const index = evalDrafts.value.findIndex((draft) => draft.id === item.id)
      if (index >= 0) evalDrafts.value[index] = result.case
      evalReviewSummary.value = result.summary
      evalReviewMessage.value = `已复核：${result.summary.human_reviewed}/200`
    } catch (caught) {
      reportError(caught, '人工复核保存失败', () => handleReviewEvalCase(item))
    } finally {
      evalReviewingId.value = ''
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
    routingMode.value = 'auto'
    topK.value = 5
    candidateK.value = 24
    vectorBalance.value = 0.38
    mmrLambda.value = 0.78
    minScore.value = 0.05
    queryRewrite.value = true
    searchMode.value = 'hybrid'
    searchProfile.value = 'balanced'
    retrievalStrategy.value = 'auto'
    graphWeight.value = 0.25
    graphMaxHops.value = 2
    parentWindow.value = 1
    modalityFilters.value = []
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
    multimodalQuery.cancel()
  })

  return {
    documents, history, overview, operations, cards, evalDrafts, metrics,
    currentRole, canEdit, canAdmin,
    selectedDocument, selectedFile, urlToImport, question, answer, selectedCitation,
    citationContext, compareResult, feedbackStats, feedbackText, feedbackMessage,
    rewriteResult, cardMessage, evalQuestion, evalKeywords, evalResults,
    evalReviewSummary, evalReviewerId, evalReviewingId, evalReviewMessage,
    realUsageConsent, realUsageSummary,
    appMode, workMode, routingMode, searchMode, searchProfile, retrievalStrategy, graphWeight,
    graphMaxHops, parentWindow, modalityFilters, topK, candidateK, vectorBalance,
    mmrLambda, minScore, queryRewrite, scopedDocumentIds, documentFilter, inspectorTab,
    booting, loading, uploading, importingUrl, comparing, rebuildingId, loadingDocument,
    loadingContext, feedbackSubmitting, rewriting, evalRunning, error, errorCode, errorRequestId,
    totalChunks, totalChars, avgQualityLabel, bm25Weight, vectorWeight, scopeSet,
    scopeLabel, filteredDocuments, isRefusal, diagnostics, citationAudit, trust,
    answerFinalized, expertParametersValid,
    boot, handleRun, cancelRun, handleUpload, handleImportUrl, handleCompare,
    selectCitation, selectDocument, openCitationElement, removeDocument, rebuildOne, rebuildAll,
    toggleScope, clearScope, useHistory, eraseHistory, handleFeedback, handleRewrite,
    handleSaveCard, handleCreateEvalCase, handleRunEvalDrafts, handleReviewEvalCase, handleDiagnosticAction,
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
    queryAttachments: multimodalQuery.attachments,
    queryAttachmentDetail: multimodalQuery.detail,
    queryAttachmentUploading: multimodalQuery.uploading,
    queryAttachmentError: multimodalQuery.error,
    queryAttachmentAudit: qualityAudit.queryAttachmentAudit,
    addQueryAttachments: multimodalQuery.addFiles,
    removeQueryAttachment: multimodalQuery.remove,
    clearQueryAttachments: multimodalQuery.clear,
    documentElements: documentViewer.elements,
    focusedElementId: documentViewer.focusedElementId,
    knowledgeGraph: graphState.graph,
    graphLoading: graphState.loading,
    graphError: graphState.error,
    refreshGraph: () => graphState.load(knowledgeBaseState.selectedKnowledgeBaseId.value),
    selectKnowledgeBase,
    addKnowledgeBase,
    startNewConversation,
    selectConversation: openConversation,
    removeConversation: conversationState.removeConversation,
  }
}

export type Workbench = ReturnType<typeof useWorkbench>
