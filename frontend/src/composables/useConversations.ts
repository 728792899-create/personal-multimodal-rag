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


export function useConversations() {
  const conversations = ref<Conversation[]>([])
  const conversationMessages = ref<ConversationMessage[]>([])
  const activeConversationId = ref('')
  const streamPhase = ref<'idle' | 'enriching' | 'retrieving' | 'streaming' | 'auditing' | 'completed' | 'failed' | 'cancelled'>('idle')
  const streamedText = ref('')
  let controller: AbortController | null = null

  async function refreshConversations() {
    conversations.value = await listConversations()
    if (activeConversationId.value && !conversations.value.some((item) => item.id === activeConversationId.value)) {
      activeConversationId.value = ''
      conversationMessages.value = []
    }
  }

  async function ensureConversation(knowledgeBaseIds: string[]) {
    const current = conversations.value.find((item) => item.id === activeConversationId.value)
    if (current && current.knowledge_base_ids.join(',') === knowledgeBaseIds.join(',')) return current
    const conversation = await createConversation('新会话', knowledgeBaseIds)
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    conversationMessages.value = []
    return conversation
  }

  async function selectConversation(id: string) {
    activeConversationId.value = id
    conversationMessages.value = await listConversationMessages(id)
  }

  async function removeConversation(id: string) {
    await deleteConversation(id)
    if (activeConversationId.value === id) {
      activeConversationId.value = ''
      conversationMessages.value = []
    }
    await refreshConversations()
  }

  async function askInConversation(
    question: string,
    knowledgeBaseIds: string[],
    retrieval: RetrievalOptions,
    attachments: QueryAttachmentRef[],
    onProgress: (event: ConversationStreamEvent, partialText: string) => void,
  ): Promise<AskResponse> {
    controller?.abort()
    controller = new AbortController()
    const conversation = await ensureConversation(knowledgeBaseIds)
    streamedText.value = ''
    streamPhase.value = 'retrieving'
    let finalResponse: AskResponse | null = null
    try {
      await streamConversationMessage(conversation.id, question, retrieval, (event) => {
        if (event.type === 'query.enrichment.started') streamPhase.value = 'enriching'
        if (event.type === 'query.enrichment.completed') streamPhase.value = 'retrieving'
        if (event.type === 'retrieval.completed') streamPhase.value = 'streaming'
        if (event.type === 'answer.delta') {
          streamedText.value += event.delta
          streamPhase.value = 'auditing'
        }
        if (event.type === 'answer.completed' || event.type === 'refusal') {
          finalResponse = event.response
          streamPhase.value = 'completed'
        }
        if (event.type === 'error') streamPhase.value = 'failed'
        onProgress(event, streamedText.value)
      }, { signal: controller.signal }, attachments)
      if (!finalResponse) throw new Error('流式回答结束但缺少最终审计结果')
      await Promise.all([refreshConversations(), selectConversation(conversation.id)])
      return finalResponse
    } catch (error) {
      streamPhase.value = error instanceof DOMException && error.name === 'AbortError' ? 'cancelled' : 'failed'
      throw error
    } finally {
      controller = null
    }
  }

  function cancelStream() {
    controller?.abort()
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
    removeConversation,
    askInConversation,
    cancelStream,
  }
}
