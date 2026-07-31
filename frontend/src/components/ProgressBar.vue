<template>
  <div class="progress-bar-container" v-if="visible">
    <div class="progress-stage">
      <el-steps :active="stageIndex" finish-status="success" align-center>
        <el-step title="上传" description="文件接收" />
        <el-step title="解析" description="提取文本" />
        <el-step title="分块" description="文本分割" />
        <el-step title="索引" description="生成向量" />
        <el-step title="完成" description="可检索" />
      </el-steps>
    </div>
    <el-progress
      :percentage="Math.round(progress * 100)"
      :status="progressStatus"
      :stroke-width="8"
    />
    <p class="progress-message">{{ message }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import type { ProgressEvent } from '@/types'

const props = defineProps<{ docId: number }>()
const emit = defineEmits<{ done: [docId: number]; error: [message: string] }>()

const visible = ref(true)
const progress = ref(0)
const message = ref('正在上传...')
const currentStage = ref('uploading')

const stageMap: Record<string, number> = {
  uploading: 0, parsing: 1, chunking: 2, indexing: 3, done: 4, error: -1,
}

const stageIndex = computed(() => stageMap[currentStage.value] ?? 0)

const progressStatus = computed(() => {
  if (currentStage.value === 'error') return 'exception'
  if (currentStage.value === 'done') return 'success'
  return undefined
})

let eventSource: EventSource | null = null

function connect() {
  const token = sessionStorage.getItem('access_token') || ''
  const url = token
    ? `/api/v1/documents/${props.docId}/progress?access_token=${encodeURIComponent(token)}`
    : `/api/v1/documents/${props.docId}/progress`
  eventSource = new EventSource(url)

  eventSource.addEventListener('progress', (e: MessageEvent) => {
    try {
      const data: ProgressEvent = JSON.parse(e.data)
      currentStage.value = data.stage
      progress.value = data.progress
      message.value = data.message
    } catch { /* ignore parse error */ }
  })

  eventSource.addEventListener('complete', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data)
      progress.value = 1
      message.value = `完成，共 ${data.chunk_count ?? '?'} 块`
      currentStage.value = 'done'
      setTimeout(() => emit('done', props.docId), 1500)
    } catch { /* ignore */ }
    eventSource?.close()
  })

  eventSource.addEventListener('error', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data)
      message.value = data.message || '解析失败'
    } catch { message.value = '连接异常' }
    currentStage.value = 'error'
    emit('error', message.value)
    eventSource?.close()
  })

  eventSource.onerror = () => {
    // EventSource 会在连接断开时自动重连
  }
}

connect()

onUnmounted(() => {
  eventSource?.close()
})
</script>

<style scoped>
.progress-bar-container { padding: 16px 0; }
.progress-stage { margin-bottom: 16px; }
.progress-message { text-align: center; color: #909399; font-size: 13px; margin-top: 8px; }
</style>
