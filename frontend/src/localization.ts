/**
 * 用户界面使用的中文语义映射。
 *
 * API 协议值、文件名和模型名称仍保持原值；这里仅用于展示固定的产品状态，
 * 避免把后端实现细节或英文枚举直接暴露给中文用户。
 */

const statusLabels: Record<string, string> = {
  active: '进行中',
  answered: '已回答',
  cancelled: '已取消',
  cancelling: '正在取消',
  checked: '已核验',
  completed: '已完成',
  configured: '已配置',
  created: '已创建',
  degraded: '已降级',
  deleted: '已删除',
  disabled: '已关闭',
  draft: '草稿',
  enabled: '已启用',
  error: '异常',
  expired: '已过期',
  failed: '失败',
  healthy: '健康',
  idle: '空闲',
  in_progress: '处理中',
  not_checked: '未检查',
  not_configured: '未配置',
  not_ready: '未就绪',
  partial: '部分完成',
  pending: '等待中',
  processing: '处理中',
  queued: '排队中',
  ready: '就绪',
  rejected: '已拒绝',
  refused: '已拒答',
  retrying: '正在重试',
  reviewed: '已复核',
  running: '处理中',
  skipped: '已跳过',
  streaming: '正在生成',
  submitted: '已提交',
  succeeded: '已完成',
  success: '成功',
  unavailable: '不可用',
  unhealthy: '异常',
  unknown: '未知',
  warning: '需注意',
  waiting: '等待中',
}

const sourceTypeLabels: Record<string, string> = {
  docx: 'DOCX 文档',
  file: '文件上传',
  image: '图像',
  local_directory: '本地目录',
  markdown: 'Markdown 文档',
  pdf: 'PDF 文档',
  rss_atom: 'RSS / Atom',
  text: '文本',
  url: '网页导入',
  url_list: 'URL 列表',
}

const elementTypeLabels: Record<string, string> = {
  code: '代码',
  equation: '公式',
  heading: '标题',
  image: '图像',
  mixed: '混合内容',
  table: '表格',
  text: '文本',
}

const parserProfileLabels: Record<string, string> = {
  auto: '自动选择',
  builtin: '内置解析器',
  docling: 'Docling',
  mineru: 'MinerU',
  paddleocr: 'PaddleOCR',
  raganything_worker: '高级解析工作进程',
  worker: '解析工作进程',
}

const providerLabels: Record<string, string> = {
  builtin: '内置',
  chroma: 'Chroma 向量库',
  disabled: '未启用',
  huggingface: '句向量模型',
  keyword: '关键词',
  local: '本地服务',
  memory: '内存',
  mock: '模拟',
  none: '未启用',
  off: '未启用',
  ollama: 'Ollama',
  ollama_vision: 'Ollama 视觉服务',
  openai_compatible_chat: '兼容 OpenAI 的对话服务',
  'openai-compatible-chat': '兼容 OpenAI 的对话服务',
  openai_compatible_vision: '兼容 OpenAI 的视觉服务',
  openai_responses: 'OpenAI 响应服务',
  'openai-responses': 'OpenAI 响应服务',
  pgvector: 'pgvector 向量库',
  raganything_worker: '高级解析工作进程',
  responses: 'OpenAI 响应服务',
  'search-only': '仅检索',
  sentence_transformers: '句向量模型',
  'sentence-transformers': '句向量模型',
  sqlite: 'SQLite',
  template: '模板',
  worker: '后台工作进程',
}

const graphNodeTypeLabels: Record<string, string> = {
  document: '文档',
  element: '文档元素',
  entity: '实体',
}

const stageLabels: Record<string, string> = {
  chunk: '分块',
  complete: '完成',
  embed: '向量化',
  enrich_modalities: '多模态增强',
  extract_elements: '提取结构化元素',
  fetch: '获取内容',
  graph_extract: '提取图谱关系',
  graph_write: '写入图谱',
  parse: '解析',
  query_rewrite: '查询改写',
  quality: '质量分析',
  scan: '安全扫描',
  store: '保存资料',
  validate: '校验',
  write: '写入',
}

const relationLabels: Record<string, string> = {
  adjacent: '相邻',
  contains: '包含',
  references: '引用',
  related_to: '关联',
  mentions: '提及',
  uses: '使用',
}

const failureTypeLabels: Record<string, string> = {
  bad_answer: '答案不准确',
  low_confidence: '置信度不足',
  no_evidence: '没有证据',
  other: '其他问题',
  retrieval_miss: '检索遗漏',
  unsupported_claim: '存在无证据主张',
  wrong_citation: '引用不准确',
}

const operationTypeLabels: Record<string, string> = {
  answer_rewritten: '已改写回答',
  document_rebuild_failed: '文档重建失败',
  eval_case_created: '已创建评测项',
  eval_drafts_run: '已运行评测草稿',
  evaluation_run: '已运行评测',
  gap_analysis_run: '已完成资料缺口分析',
  history_cleared: '已清空问答历史',
  knowledge_card_created: '已保存知识卡片',
  knowledge_card_deleted: '已删除知识卡片',
  'index_job.queued': '索引任务已入队',
  'index_job.retry_requested': '已请求重试索引任务',
  'index_job.retry_scheduled': '索引任务已安排重试',
  url_deduped: '网页资料已存在',
  url_import_failed: '网页导入失败',
}

const errorExactLabels: Record<string, string> = {
  'Invalid administrator credentials': '管理员密码不正确。',
  'Request cancelled': '请求已取消。',
  'Request timed out': '请求超时，请重试。',
  'Rate limit exceeded': '请求过于频繁，请稍后重试。',
  'source service unavailable': '数据源服务暂时不可用，请稍后重试。',
  'Workspace unavailable': '工作区暂时不可用，请稍后重试。',
}

const systemTermLabels: Record<string, string> = {
  answer: '回答',
  bm25: 'BM25',
  citation: '引用',
  embedding: '嵌入',
  evidence: '证据',
  fallback: '降级处理',
  graph: '图谱',
  keyword: '关键词检索',
  parser: '解析器',
  provider: '服务提供方',
  rerank: '重排序',
  retrieval: '检索',
  semantic: '语义检索',
  vector: '向量',
}

function containsChinese(value: string) {
  return /[\u3400-\u9fff]/.test(value)
}

export function localizedStatus(value?: string | null, fallback = '—') {
  const normalized = String(value || '').trim()
  if (!normalized) return fallback
  return statusLabels[normalized.toLowerCase()] || normalized
}

export function localizedSourceType(value?: string | null) {
  const normalized = String(value || '').trim()
  return sourceTypeLabels[normalized.toLowerCase()] || normalized || '未知来源'
}

export function localizedElementType(value?: string | null) {
  const normalized = String(value || '').trim()
  return elementTypeLabels[normalized.toLowerCase()] || normalized || '未知元素'
}

export function localizedParserProfile(value?: unknown) {
  const normalized = typeof value === 'string' ? value.trim() : ''
  return parserProfileLabels[normalized.toLowerCase()] || normalized || '未指定'
}

export function localizedProvider(value?: string | null) {
  const normalized = String(value || '').trim()
  return providerLabels[normalized.toLowerCase()] || normalized || '未指定'
}

export function localizedQueryRewriter(value?: string | null) {
  const normalized = String(value || '').trim().toLowerCase()
  const labels: Record<string, string> = {
    disabled: '未启用',
    none: '未启用',
    noop: '未启用',
    off: '未启用',
    query_rewriter: '查询改写器',
  }
  return labels[normalized] || localizedProvider(normalized)
}

export function localizedGraphNodeType(value?: string | null) {
  const normalized = String(value || '').trim()
  return graphNodeTypeLabels[normalized.toLowerCase()] || normalized || '节点'
}

export function localizedIndexStage(value?: string | null) {
  const normalized = String(value || '').trim()
  return stageLabels[normalized.toLowerCase()] || localizedStatus(normalized, '等待中')
}

export function localizedSearchProfile(value?: string | null) {
  const labels: Record<string, string> = {
    balanced: '均衡',
    precision: '精准',
    recall: '召回优先',
  }
  const normalized = String(value || '').trim()
  return labels[normalized.toLowerCase()] || normalized || '均衡'
}

export function localizedSearchMode(value?: string | null) {
  const labels: Record<string, string> = {
    hybrid: '混合检索',
    keyword: '关键词检索',
    semantic: '语义检索',
  }
  const normalized = String(value || '').trim()
  return labels[normalized.toLowerCase()] || normalized || '混合检索'
}

export function localizedRetrievalStrategy(value?: string | null) {
  const labels: Record<string, string> = {
    auto: '自动识别',
    hybrid: '混合检索',
    hybrid_graph: '混合检索与图谱',
  }
  const normalized = String(value || '').trim()
  return labels[normalized.toLowerCase()] || normalized || '自动识别'
}

export function localizedCompareProfile(id?: string | null, label?: string | null) {
  const labels: Record<string, string> = {
    hybrid: '混合检索',
    hybrid_rerank: '混合检索与重排序',
    keyword: '关键词 BM25',
    semantic: '语义向量',
  }
  const normalized = String(id || '').trim().toLowerCase()
  if (labels[normalized]) return labels[normalized]
  return String(label || '').replace(/rerank/gi, '重排序') || '检索策略'
}

export function localizedRelation(value?: string | null) {
  const normalized = String(value || '').trim()
  return relationLabels[normalized.toLowerCase()] || normalized || '关联'
}

export function localizedFailureType(value?: string | null) {
  const normalized = String(value || '').trim()
  return failureTypeLabels[normalized.toLowerCase()] || localizedStatus(normalized, '待复核')
}

export function localizedOperationType(value?: string | null) {
  const normalized = String(value || '').trim()
  return operationTypeLabels[normalized.toLowerCase()] || normalized || '系统操作'
}

/**
 * 原始 API detail 可能包含服务端英文、路径或实现措辞。中文 detail 会保留；
 * 未识别的英文 detail 使用调用点的中文回退语，错误码与请求 ID 则独立展示。
 */
export function localizedErrorMessage(message: unknown, fallback: string) {
  const text = typeof message === 'string' ? message.trim() : ''
  if (!text) return fallback
  if (containsChinese(text)) return text
  if (errorExactLabels[text]) return errorExactLabels[text]
  const lowered = text.toLowerCase()
  if (lowered.includes('rate limit') || lowered.includes('too many request')) return '请求过于频繁，请稍后重试。'
  if (lowered.includes('credential') || lowered.includes('authentication') || lowered.includes('unauthorized')) return '身份验证失败，请检查登录状态或管理员密码。'
  if (lowered.includes('csrf')) return '安全校验未通过，请刷新页面后重试。'
  if (lowered.includes('not found')) return '请求的资源不存在或已被删除。'
  if (lowered.includes('forbidden') || lowered.includes('permission')) return '当前会话没有执行此操作的权限。'
  if (lowered.includes('timeout') || lowered.includes('timed out')) return '请求超时，请稍后重试。'
  if (lowered.includes('network') || lowered.includes('failed to fetch') || lowered.includes('connection')) return '网络连接异常，请检查服务后重试。'
  if (lowered.includes('unavailable') || lowered.includes('provider') || lowered.includes('service')) return '服务暂时不可用，请稍后重试。'
  if (lowered.includes('cancel')) return '请求已取消。'
  return fallback
}

/** 仅用于服务端生成的诊断、操作与状态文案；不应用于用户上传的正文或文件名。 */
export function localizedSystemText(message: unknown, fallback: string) {
  const raw = typeof message === 'string' ? message.trim() : ''
  const resolved = systemTermLabels[raw.toLowerCase()] || localizedErrorMessage(raw, fallback)
  return resolved
    .replace(/\banswer\b/gi, '回答')
    .replace(/\bcase\b/gi, '评测项')
    .replace(/\bcitation\b/gi, '引用')
    .replace(/\bembedding\b/gi, '嵌入')
    .replace(/\bevidence\b/gi, '证据')
    .replace(/\bfallback\b/gi, '降级处理')
    .replace(/\bgraph\b/gi, '图谱')
    .replace(/\bmodel\b/gi, '模型')
    .replace(/\bparser\b/gi, '解析器')
    .replace(/\bprovider\b/gi, '服务提供方')
    .replace(/\bretrieval\b/gi, '检索')
    .replace(/\brerank\b/gi, '重排序')
    .replace(/\breviewer\b/gi, '复核人')
    .replace(/\btrace\b/gi, '过程')
    .replace(/\bvector\b/gi, '向量')
    .replace(/\bquery[_ -]?rewrite(?:r)?\b/gi, '查询改写')
    .replace(/\bworker\b/gi, '工作进程')
    .replace(/\bopenai[_ -]?responses\b/gi, 'OpenAI 响应服务')
    .replace(/\bopenai[_ -]?compatible[_ -]?(?:chat|vision)\b/gi, '兼容 OpenAI 的服务')
    .replace(/\bsentence[_ -]?transformers\b/gi, '句向量模型')
    .replace(/\bhuggingface\b/gi, '句向量模型')
    .replace(/\bpgvector\b/gi, 'pgvector 向量库')
    .replace(/\bchroma\b/gi, 'Chroma 向量库')
}
