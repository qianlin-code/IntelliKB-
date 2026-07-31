import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { KnowledgeBase, KBCreate, KBUpdate } from '@/types'
import { createKBApi, listKBsApi, getKBApi, updateKBApi, deleteKBApi } from '@/api/knowledgeBase'
import { ElMessage } from 'element-plus'

export const useKBStore = defineStore('kb', () => {
  const kbList = ref<KnowledgeBase[]>([])
  const currentKB = ref<KnowledgeBase | null>(null)
  const loading = ref(false)

  async function fetchKBList(page = 1, pageSize = 20) {
    loading.value = true
    try {
      const resp = await listKBsApi(page, pageSize)
      kbList.value = resp.data.items
      return { items: resp.data.items, total: resp.data.total }
    } finally {
      loading.value = false
    }
  }

  async function fetchKB(kbId: number) {
    const resp = await getKBApi(kbId)
    currentKB.value = resp.data
    return resp.data
  }

  async function createKB(data: KBCreate) {
    const resp = await createKBApi(data)
    ElMessage.success('知识库创建成功')
    await fetchKBList()
    return resp.data
  }

  async function updateKB(kbId: number, data: KBUpdate) {
    const resp = await updateKBApi(kbId, data)
    ElMessage.success('知识库已更新')
    if (currentKB.value?.id === kbId) {
      currentKB.value = resp.data
    }
    return resp.data
  }

  async function removeKB(kbId: number) {
    await deleteKBApi(kbId)
    ElMessage.success('知识库已删除')
    kbList.value = kbList.value.filter(k => k.id !== kbId)
    if (currentKB.value?.id === kbId) {
      currentKB.value = null
    }
  }

  return { kbList, currentKB, loading, fetchKBList, fetchKB, createKB, updateKB, removeKB }
})
