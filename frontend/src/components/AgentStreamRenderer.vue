<template>
  <div class="agent-stream-renderer">
    <!-- 思考过程 -->
    <div v-if="thought" class="stream-thought">
      <el-icon class="is-loading" :size="14"><Loading /></el-icon>
      <span>{{ thought }}</span>
    </div>

    <!-- 工具调用 -->
    <div v-if="toolCalls.length > 0" class="stream-tool-calls">
      <ToolCallCard
        v-for="(tc, idx) in toolCalls"
        :key="idx"
        :tool="tc.tool"
        :input="tc.input"
        :output="tc.output"
      />
    </div>

    <!-- Token 流式输出 (Phase 4: Markdown 渲染) -->
    <div v-if="streamContent" class="stream-content">
      <div class="stream-text markdown-body" v-html="renderedContent"></div>
    </div>

    <!-- 来源引用 -->
    <div v-if="sources.length > 0 && !streaming" class="stream-sources">
      <el-collapse>
        <el-collapse-item :title="`参考来源 (${sources.length})`">
          <div v-for="s in sources" :key="s.chunk_id" class="source-item">
            <div class="source-header">
              <span>文档 #{{ s.document_id }}</span>
              <span class="source-score">相关度: {{ (s.score * 100).toFixed(1) }}%</span>
            </div>
            <div class="source-content">{{ s.content }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 错误 -->
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon style="margin-top: 8px" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import type { SearchResult, ToolCallInfo } from '@/types'
import ToolCallCard from './ToolCallCard.vue'
import { renderMarkdown } from '@/composables/useMarkdown'

const props = defineProps<{
  streaming?: boolean
}>()

const emit = defineEmits<{
  done: [data: { conversation_id: number; total_tokens: number; tool_calls_count: number }]
  token: [content: string]
}>()

const thought = ref('')
const toolCalls = ref<ToolCallInfo[]>([])
const streamContent = ref('')
const sources = ref<SearchResult[]>([])
const error = ref('')
const streaming = computed(() => props.streaming !== false)

// Phase 4: Markdown 渲染
const renderedContent = computed(() => renderMarkdown(streamContent.value))

function handleEvent(event: string, data: string): boolean {
  try {
    const parsed = JSON.parse(data)

    switch (event) {
      case 'thought':
        thought.value = parsed.content || ''
        return true

      case 'tool_call':
        toolCalls.value.push({
          tool: parsed.tool || '',
          input: parsed.input || {},
          output: '',
        })
        return true

      case 'tool_result': {
        const lastIdx = toolCalls.value.length - 1
        if (lastIdx >= 0 && toolCalls.value[lastIdx].tool === parsed.tool) {
          toolCalls.value[lastIdx].output = parsed.output || ''
        }
        return true
      }

      case 'sources':
        sources.value = parsed.sources || []
        return true

      case 'done':
        emit('done', {
          conversation_id: parsed.conversation_id,
          total_tokens: parsed.total_tokens,
          tool_calls_count: parsed.tool_calls_count,
        })
        return false // 流结束

      case 'error':
        error.value = parsed.message || 'Agent 处理出错'
        return false

      default:
        // 纯 data: 事件（token 流）
        if (!event && data) {
          streamContent.value += data
          emit('token', data)
          return true
        }
        return true
    }
  } catch (e) {
    console.warn('AgentStreamRenderer: 事件解析失败', event, data, e)
    return true
  }
}

function reset() {
  thought.value = ''
  toolCalls.value = []
  streamContent.value = ''
  sources.value = []
  error.value = ''
}

/**
 * Phase 4: 使用统一 useSSE 模式的 frame 解析
 * 按 \n\n 切分 frame，支持多行 data 拼接
 */
function handleSSEFrame(frame: string): boolean {
  if (!frame.trim()) return true

  let eventType = ''
  const dataLines: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  const data = dataLines.join('\n')
  if (!data) return true

  return handleEvent(eventType, data)
}

/**
 * 处理 fetch SSE 的原始帧（向后兼容旧接口）
 */
function handleRawChunk(chunk: string): boolean {
  try {
    const frames = chunk.split('\n\n')
    for (const frame of frames) {
      if (!handleSSEFrame(frame)) {
        return false
      }
    }
    return true
  } catch (e) {
    console.warn('AgentStreamRenderer: 原始帧解析失败', e)
    return true
  }
}

defineExpose({ handleEvent, handleSSEFrame, handleRawChunk, reset })
</script>

<style scoped>
.agent-stream-renderer {
  padding: 8px 0;
}
.stream-thought {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 13px;
  padding: 8px 0;
}
.stream-tool-calls {
  margin: 8px 0;
}
.stream-content {
  margin-top: 12px;
}
.stream-text {
  line-height: 1.6;
  font-size: 14px;
  color: #303133;
}

/* Phase 4: Markdown 样式 */
.markdown-body :deep(p) { margin: 0.5em 0; }
.markdown-body :deep(pre) { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.markdown-body :deep(code) { font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; }
.markdown-body :deep(p > code) { background: #f0f2f5; padding: 2px 6px; border-radius: 4px; }
.markdown-body :deep(table) { border-collapse: collapse; margin: 8px 0; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #e4e7ed; padding: 6px 12px; text-align: left; }

.stream-sources {
  margin-top: 16px;
}
.source-item {
  margin-bottom: 8px;
  padding: 8px;
  background: #fff;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}
.source-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.source-score {
  color: #e6a23c;
}
.source-content {
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
}
</style>
