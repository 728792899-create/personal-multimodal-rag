import { ref } from 'vue'

import {
  createConversation,
  deleteConversation,
  listConversationMessages,
  listConversations,
  streamConversationMessage,
  type AskResponse,
  type Conversation,
  type ConversationMessage,
  type ConversationStreamEvent,
  type QueryAttachmentRef,
  type RetrievalOptions,
} from '../api'

const ACTIVE_CONVERSATION_STORAGE_KEY = '知证.active-conversation.v1'

function storedConversationId() {
  try {
    return window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function rememberConversation(id: string) {
  try {
    if (id) window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, id)
    else window.localStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY)
  } catch {
    // Storage can be blocked by browser privacy settings. Server-side
    // conversations remain available through the conversation list.
  }
}

export function useConversations() {
  const conversations = ref<Conversation[]>([])
  const conversationMessages = ref<ConversationMessage[]>([])
  const activeConversationId = ref('')
  const streamPhase = ref<'idle' | 'enriching' | 'retrieving' | 'streaming' | 'auditing' | 'completed' | 'failed' | 'cancelled'>('idle')
  const streamedText = ref('')
  let controller: AbortController | null = null
  let streamGeneration = 0

  async function refreshConversations() {
    conversations.value = await listConversations()
    if (activeConversationId.value && !conversations.value.some((item) => item.id === activeConversationId.value)) {
      activeConversationId.value = ''
      conversationMessages.value = []
      rememberConversation('')
    }
  }

  async function ensureConversation(knowledgeBaseIds: string[]) {
    const current = conversations.value.find((item) => item.id === activeConversationId.value)
    if (current && current.knowledge_base_ids.join(',') === knowledgeBaseIds.join(',')) return current
    const conversation = await createConversation('新会话', knowledgeBaseIds)
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    conversationMessages.value = []
    rememberConversation(conversation.id)
    return conversation
  }

  async function selectConversation(id: string) {
    const messages = await listConversationMessages(id)
    activeConversationId.value = id
    conversationMessages.value = messages
    const lastAssistant = [...messages].reverse().find((item) => item.role === 'assistant')
    streamPhase.value = lastAssistant?.status === 'failed'
      ? 'failed'
      : lastAssistant?.status === 'cancelled'
        ? 'cancelled'
        : lastAssistant?.status === 'completed'
          ? 'completed'
          : 'idle'
    rememberConversation(id)
  }

  async function restoreActiveConversation() {
    const savedId = storedConversationId()
    if (!savedId || !conversations.value.some((item) => item.id === savedId)) {
      if (savedId) rememberConversation('')
      return false
    }
    await selectConversation(savedId)
    return true
  }

  function clearActiveConversation() {
    activeConversationId.value = ''
    conversationMessages.value = []
    streamPhase.value = 'idle'
    streamedText.value = ''
    rememberConversation('')
  }

  async function removeConversation(id: string) {
    await deleteConversation(id)
    if (activeConversationId.value === id) {
      clearActiveConversation()
    }
    await refreshConversations()
  }

  async function askInConversation(
    question: string,
    knowledgeBaseIds: string[],
    retrieval: RetrievalOptions,
    attachments: QueryAttachmentRef[],
    recordAsRealUsage: boolean,
    onProgress: (event: ConversationStreamEvent, partialText: string) => void,
  ): Promise<AskResponse> {
    const generation = ++streamGeneration
    controller?.abort()
    const requestController = new AbortController()
    controller = requestController
    const conversation = await ensureConversation(knowledgeBaseIds)
    if (generation === streamGeneration) {
      streamedText.value = ''
      streamPhase.value = 'retrieving'
    }
    let finalResponse: AskResponse | null = null
    try {
      await streamConversationMessage(conversation.id, question, retrieval, (event) => {
        if (generation !== streamGeneration) return
        if (event.type === 'query.enrichment.started') streamPhase.value = 'enriching'
        if (event.type === 'query.enrichment.completed') streamPhase.value = 'retrieving'
        if (event.type === 'retrieval.completed') streamPhase.value = 'streaming'
        if (event.type === 'answer.delta') {
          streamedText.value += event.delta
          streamPhase.value = 'streaming'
        }
        if (event.type === 'answer.completed' || event.type === 'refusal') {
          finalResponse = event.response
          streamPhase.value = 'completed'
        }
        if (event.type === 'error') streamPhase.value = 'failed'
        onProgress(event, streamedText.value)
      }, { signal: requestController.signal }, attachments, recordAsRealUsage)
      if (!finalResponse) throw new Error('流式回答结束但缺少最终审计结果')
      if (generation === streamGeneration) {
        // Sidebar/message refresh is secondary to the already-audited answer. A
        // transient follow-up read must not turn a successful answer into an error.
        await refreshConversations().catch(() => undefined)
        await selectConversation(conversation.id).catch(() => undefined)
      }
      return finalResponse
    } catch (error) {
      if (generation === streamGeneration) {
        streamPhase.value = error instanceof DOMException && error.name === 'AbortError' ? 'cancelled' : 'failed'
      }
      if (generation === streamGeneration && !(error instanceof DOMException && error.name === 'AbortError')) {
        await refreshConversations().catch(() => undefined)
        await selectConversation(conversation.id).catch(() => undefined)
      }
      throw error
    } finally {
      if (controller === requestController) controller = null
    }
  }

  function cancelStream() {
    streamGeneration += 1
    const current = controller
    controller = null
    current?.abort()
    streamPhase.value = 'cancelled'
  }

  return {
    conversations,
    conversationMessages,
    activeConversationId,
    streamPhase,
    streamedText,
    refreshConversations,
    selectConversation,
    restoreActiveConversation,
    clearActiveConversation,
    removeConversation,
    askInConversation,
    cancelStream,
  }
}
