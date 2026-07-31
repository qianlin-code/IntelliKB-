import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { SearchResult } from '@/types'

interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export const useQAStore = defineStore('qa', () => {
  const history = ref<HistoryMessage[]>([])
  const lastSources = ref<SearchResult[]>([])

  function addUserMessage(content: string) {
    history.value.push({ role: 'user', content })
  }

  function addAssistantMessage(content: string) {
    if (content) {
      history.value.push({ role: 'assistant', content })
    }
  }

  function setSources(sources: SearchResult[]) {
    lastSources.value = sources
  }

  function clearHistory() {
    history.value = []
    lastSources.value = []
  }

  return { history, lastSources, addUserMessage, addAssistantMessage, setSources, clearHistory }
})
