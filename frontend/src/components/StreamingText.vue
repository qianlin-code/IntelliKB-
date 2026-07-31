<template>
  <div class="streaming-text">
    <div v-if="sources.length" class="sources-section">
      <el-collapse>
        <el-collapse-item :title="`参考来源 (${sources.length})`">
          <div v-for="(s, i) in sources" :key="i" class="source-item">
            <span class="source-label">[来源 {{ i + 1 }}] 文档 #{{ s.document_id }}</span>
            <span class="source-score">相关度 {{ (s.score * 100).toFixed(1) }}%</span>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>
    <div class="answer-text" v-html="renderedContent"></div>
    <div v-if="streaming" class="typing-indicator">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
    <div v-if="error" class="error-box">
      <el-alert :title="error" type="warning" show-icon :closable="false" />
    </div>
    <el-button v-if="streaming" type="danger" size="small" @click="abort" style="margin-top: 8px">
      停止生成
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useMarkdown } from '@/composables/useMarkdown'
import { useSSE, SSEError } from '@/composables/useSSE'
import type { SearchResult } from '@/types'

const props = defineProps<{
  url: string
  body?: Record<string, unknown>
  kbId?: number
  question?: string
  topK?: number
}>()

const emit = defineEmits<{ done: [text: string]; error: [err: Error] }>()

const sources = ref<SearchResult[]>([])
const text = ref('')
const streaming = ref(true)
const error = ref('')

let abortController: AbortController | null = null
let abortedByUser = false

// Phase 4: 使用统一的 useMarkdown composable
const { renderedContent } = useMarkdown(() => text.value)

async function start() {
  abortController = new AbortController()
  abortedByUser = false

  // 兼容旧版 props：如果未传 body，从 kbId/question/topK 构造
  const body = props.body ?? {
    kb_id: props.kbId,
    question: props.question,
    top_k: props.topK ?? 5,
  }

  // SSE 无法携带 Authorization header，通过 access_token query param 认证
  const token = sessionStorage.getItem('access_token') || ''

  try {
    const { stream } = useSSE(props.url, {
      signal: abortController.signal,
      method: props.body ? 'POST' : 'GET',
      body: props.body ? body : undefined,
      token,
    })

    for await (const { event, data } of stream()) {
      if (event === 'sources') {
        try {
          sources.value = JSON.parse(data).sources || []
        } catch {
          // ignore
        }
        continue
      }
      if (event === 'done') {
        streaming.value = false
        emit('done', text.value)
        return
      }
      if (event === 'error') {
        streaming.value = false
        try {
          const parsed = JSON.parse(data)
          error.value = parsed.message || '生成失败'
        } catch {
          error.value = '生成失败'
        }
        emit('error', new Error(error.value))
        return
      }
      if (!event && data) {
        try {
          const token = JSON.parse(data)
          text.value += token
        } catch {
          text.value += data
        }
      }
    }
  } catch (e: any) {
    // 仅忽略用户主动点击"停止"产生的 AbortError；
    // 网络异常若被浏览器报告为 AbortError，仍应触发错误回调以走 fallback。
    console.error('[StreamingText] SSE fetch error:', e?.name, e?.message, e)
    if (e.name === 'AbortError' && abortedByUser) return
    const msg = e instanceof SSEError ? e.message : `连接异常: ${e.message}`
    error.value = msg
    emit('error', e instanceof Error ? e : new Error(msg))
  } finally {
    streaming.value = false
  }
}

function abort() {
  abortedByUser = true
  abortController?.abort()
  streaming.value = false
}

start()

onUnmounted(() => {
  abortController?.abort()
})
</script>

<style scoped>
.streaming-text { }
.sources-section { margin-bottom: 16px; }
.source-item { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.source-label { color: #409eff; }
.source-score { color: #909399; }
.answer-text { line-height: 1.8; font-size: 15px; color: #303133; }
.answer-text :deep(p) { margin: 8px 0; }
.answer-text :deep(pre) { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
.answer-text :deep(code) { background: #f0f2f5; padding: 2px 6px; border-radius: 4px; }
.typing-indicator { display: inline-flex; gap: 4px; padding: 4px 0; }
.dot { width: 6px; height: 6px; background: #409eff; border-radius: 50%; animation: blink 1.4s infinite both; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.2; } 40% { opacity: 1; } }
.error-box { margin: 12px 0; }
</style>
