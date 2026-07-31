import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation, Message, SearchResult, ToolCallInfo } from '@/types'
import {
  listConversationsApi,
  createConversationApi,
  deleteConversationApi,
  updateConversationApi,
  pinConversationApi,
  getMessagesApi,
  regenerateMessageApi,
  forkConversationApi,
} from '@/api/conversation'

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  const currentConvId = ref<number | null>(null)
  const messages = ref<Message[]>([])
  const totalConv = ref(0)
  const loading = ref(false)

  async function loadConversations(
    kbId: number, page = 1, pageSize = 50,
    search?: string, startDate?: string, endDate?: string,
  ) {
    loading.value = true
    try {
      const resp = await listConversationsApi(kbId, page, pageSize, search, startDate, endDate)
      conversations.value = resp.data.items
      totalConv.value = resp.data.total
    } finally {
      loading.value = false
    }
  }

  async function createConversation(kbId: number, title?: string) {
    const resp = await createConversationApi({ kb_id: kbId, title })
    conversations.value.unshift(resp.data)
    currentConvId.value = resp.data.id
    messages.value = []
    return resp.data
  }

  async function deleteConversation(convId: number) {
    await deleteConversationApi(convId)
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (currentConvId.value === convId) {
      currentConvId.value = null
      messages.value = []
    }
  }

  async function updateTitle(convId: number, title: string) {
    const resp = await updateConversationApi(convId, { title })
    const idx = conversations.value.findIndex(c => c.id === convId)
    if (idx >= 0) {
      conversations.value[idx] = resp.data
    }
    return resp.data
  }

  async function pinConversation(convId: number, isPinned: boolean) {
    const resp = await pinConversationApi(convId, isPinned)
    const idx = conversations.value.findIndex(c => c.id === convId)
    if (idx >= 0) {
      conversations.value[idx] = resp.data
    }
  }

  async function loadMessages(convId: number) {
    const resp = await getMessagesApi(convId)
    messages.value = resp.data.items.map(m => ({
      ...m,
      metadata_json: m.metadata_json || undefined,
    }))
  }

  function appendMessage(msg: Message) {
    messages.value.push(msg)
  }

  function appendAssistantMessage(content: string, toolCalls?: ToolCallInfo[], sources?: SearchResult[]) {
    const msg: Message = {
      id: Date.now(), // 临时 ID
      conversation_id: currentConvId.value || 0,
      role: 'assistant',
      content,
      metadata_json: toolCalls ? { tool_calls_log: toolCalls, sources } : undefined,
      token_count: 0,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
  }

  function appendUserMessage(content: string) {
    const msg: Message = {
      id: Date.now() + 1,
      conversation_id: currentConvId.value || 0,
      role: 'user',
      content,
      token_count: 0,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
  }

  async function regenerateMessage(convId: number, msgId: number, editedQuestion: string) {
    const resp = await regenerateMessageApi(convId, msgId, editedQuestion)
    await loadMessages(convId)
    return resp.data
  }

  async function forkConversation(convId: number, messageId: number) {
    const resp = await forkConversationApi(convId, messageId)
    // 刷新列表并切换到新分支
    if (currentConvId.value) {
      await loadConversations(conversations.value.find(c => c.id === currentConvId.value)?.kb_id || 0)
    }
    currentConvId.value = resp.data.new_conversation_id
    await loadMessages(resp.data.new_conversation_id)
    return resp.data
  }

  function setCurrentConv(convId: number) {
    currentConvId.value = convId
  }

  function clearConversations() {
    conversations.value = []
    currentConvId.value = null
    messages.value = []
    totalConv.value = 0
  }

  return {
    conversations, currentConvId, messages, totalConv, loading,
    loadConversations, createConversation, deleteConversation,
    updateTitle, pinConversation, loadMessages, appendMessage, appendAssistantMessage,
    appendUserMessage, regenerateMessage, forkConversation,
    setCurrentConv, clearConversations,
  }
})
