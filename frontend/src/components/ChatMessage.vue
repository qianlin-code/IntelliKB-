<template>
  <div class="chat-message" :class="`role-${role}`">
    <div class="message-avatar">
      <el-avatar :size="32" :icon="isUser ? 'UserFilled' : 'ChatDotSquare'" :style="avatarStyle" />
    </div>
    <div class="message-body">
      <div class="message-role-label">
        {{ roleLabel }}
        <!-- Phase P0: 消息操作 -->
        <span v-if="props.convId && props.msgId" class="message-actions">
          <el-button
            v-if="isUser"
            size="small"
            text
            @click="onEditRegenerate"
            title="编辑并重新生成"
          >编辑</el-button>
          <el-button
            v-if="!isUser && role === 'assistant'"
            size="small"
            text
            @click="emit('regenerate', props.msgId, '')"
            title="重新生成"
          >重新生成</el-button>
          <el-button
            size="small"
            text
            @click="emit('fork', props.msgId)"
            title="从此消息创建分支"
          >分叉</el-button>
        </span>
      </div>
      <div class="message-content">
        <!-- User message: plain text -->
        <template v-if="role === 'user'">
          <div class="text-content">{{ content }}</div>
        </template>

        <!-- Assistant message: markdown rendering (Phase 4 + Phase 8 citation) -->
        <template v-if="role === 'assistant'">
          <div
            v-if="content"
            class="markdown-body"
            v-html="renderedContent"
            @click="onContentClick"
          ></div>
          <!-- Phase 8: 内联引用弹窗 -->
          <teleport to="body">
            <div
              v-if="citationPopover.visible"
              class="citation-popover"
              :style="{ top: citationPopover.y + 'px', left: citationPopover.x + 'px' }"
              @click.stop
            >
              <div class="citation-popover-header">
                <el-tag size="small" type="info">来源 {{ citationPopover.index }}</el-tag>
                <span v-if="citationPopover.source?.document_id" class="source-doc-id">
                  文档 #{{ citationPopover.source.document_id }}
                </span>
              </div>
              <div class="citation-popover-text">{{ citationPopover.source?.content || '(内容不可用)' }}</div>
            </div>
          </teleport>
          <div v-if="toolCalls && toolCalls.length > 0" class="tool-calls-area">
            <ToolCallCard
              v-for="(tc, idx) in toolCalls"
              :key="idx"
              :tool="tc.tool"
              :input="tc.input"
              :output="tc.output"
            />
          </div>
          <!-- Phase 8 P1.3 + Phase 9 P1.4: 推荐问题 + 刷新 -->
          <div v-if="followUpQuestions && followUpQuestions.length > 0" class="follow-up-area">
            <div class="follow-up-label">
              💡 继续探索
              <el-button text size="small" :icon="Refresh" @click="emit('refresh-follow-up')" title="换一批" style="margin-left:6px" />
            </div>
            <div class="follow-up-chips">
              <el-button
                v-for="(q, idx) in followUpQuestions"
                :key="idx"
                size="small"
                plain
                type="primary"
                @click="emit('follow-up', q)"
              >
                {{ q }}
              </el-button>
            </div>
          </div>
          <!-- Phase 9: 来源面板（双向高亮交互） -->
          <SourcePanel
            v-if="sources && sources.length > 0"
            :sources="sources"
            :highlighted-index="hoveredCitationIndex"
            @source-click="onSourcePanelClick"
            @source-hover="onSourcePanelHover"
          />
          <div v-if="sources && sources.length > 0" class="sources-area">
            <el-collapse>
              <el-collapse-item :title="`参考来源 (${sources.length})`">
                <div v-for="(s, i) in sources" :key="s.chunk_id" class="source-item" :id="`source-${i + 1}`">
                  <div class="source-header">
                    <span>文档 #{{ s.document_id }} <el-tag size="small" type="warning">[{{ i + 1 }}]</el-tag></span>
                    <span class="source-score">相关度: {{ (s.score * 100).toFixed(1) }}%</span>
                  </div>
                  <div class="source-content">{{ s.content }}</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>

        <!-- Tool call messages -->
        <template v-if="role === 'tool_call' || role === 'tool_result'">
          <div class="text-content text-muted">{{ content }}</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import type { SearchResult, ToolCallInfo } from '@/types'
import ToolCallCard from './ToolCallCard.vue'
import { renderMarkdown } from '@/composables/useMarkdown'
import { preprocessCitations, extractCitationIndices } from '@/composables/useCitations'
import { Refresh } from '@element-plus/icons-vue'
import SourcePanel from './SourcePanel.vue'
import { ElMessageBox } from 'element-plus'

interface Props {
  role: string
  content: string
  msgId?: number
  convId?: number
  toolCalls?: ToolCallInfo[]
  sources?: SearchResult[]
  followUpQuestions?: string[]  // Phase 8 P1.3
}

const emit = defineEmits<{
  'follow-up': [question: string]
  'refresh-follow-up': []
  'regenerate': [msgId: number, editedQuestion: string]
  'fork': [msgId: number]
}>()

const props = defineProps<Props>()

const isUser = computed(() => props.role === 'user')

const roleLabel = computed(() => {
  switch (props.role) {
    case 'user': return '你'
    case 'assistant': return 'AI 助手'
    case 'tool_call': return '工具调用'
    case 'tool_result': return '工具结果'
    default: return props.role
  }
})

const avatarStyle = computed(() => ({
  background: isUser.value ? '#409eff' : '#67c23a',
}))

// Phase 4 + Phase 8: Markdown 渲染（预处理 [source:N] 引用标记）
const renderedContent = computed(() => {
  if (props.role !== 'assistant' || !props.content) return ''
  const processed = preprocessCitations(props.content)
  return renderMarkdown(processed)
})

// Phase 8: 内联引用点击处理
const citationPopover = reactive({
  visible: false,
  index: 0,
  x: 0,
  y: 0,
  source: null as SearchResult | null,
})

// Phase 9: 双向高亮
const hoveredCitationIndex = ref<number | null>(null)

function onContentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.classList.contains('src-ref')) {
    const srcIndex = parseInt(target.dataset.src || '0')
    if (srcIndex > 0 && props.sources) {
      const source = props.sources[srcIndex - 1] || null
      const rect = target.getBoundingClientRect()
      citationPopover.index = srcIndex
      citationPopover.source = source
      citationPopover.x = rect.left
      citationPopover.y = rect.bottom + 4
      citationPopover.visible = true
    }
  } else {
    citationPopover.visible = false
  }
}

// Phase 9: SourcePanel click → highlight inline citation
function onSourcePanelClick(index: number) {
  const el = document.querySelector(`.src-ref[data-src="${index}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('src-ref-flash')
    setTimeout(() => el.classList.remove('src-ref-flash'), 1500)
  }
}

// Phase 9: SourcePanel hover → highlight inline citation
function onSourcePanelHover(index: number | null) {
  hoveredCitationIndex.value = index
}

function onDocumentClick() {
  citationPopover.visible = false
}

async function onEditRegenerate() {
  try {
    const { value } = await ElMessageBox.prompt('编辑问题后将从该位置重新生成回答', '编辑并重新生成', {
      inputValue: props.content,
      confirmButtonText: '重新生成',
      cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim() ? true : '问题不能为空'),
    })
    if (props.msgId !== undefined) {
      emit('regenerate', props.msgId, value.trim())
    }
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  padding: 16px 0;
}
.chat-message.role-user {
  flex-direction: row-reverse;
}
.message-avatar {
  flex-shrink: 0;
}
.message-body {
  max-width: 75%;
}
.role-user .message-body {
  text-align: right;
}
.message-role-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.message-actions {
  display: none;
  gap: 2px;
}
.message-body:hover .message-actions {
  display: inline-flex;
}
.message-content {
  background: #f5f7fa;
  padding: 12px 16px;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
}
.role-user .message-content {
  background: #ecf5ff;
  text-align: left;
}
.role-assistant .message-content {
  background: #f0f9eb;
}
.text-content {
  white-space: pre-wrap;
  word-break: break-word;
}
.text-muted {
  color: #909399;
  font-style: italic;
  font-size: 13px;
}

/* Phase 4: Markdown 内容样式 */
.markdown-body :deep(p) {
  margin: 0.5em 0;
}
.markdown-body :deep(pre) {
  background: #f6f8fa;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.markdown-body :deep(code) {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
}
.markdown-body :deep(p > code) {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e4e7ed;
  padding: 6px 12px;
  text-align: left;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
}

.tool-calls-area {
  margin-top: 8px;
}
.sources-area {
  margin-top: 8px;
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

/* Phase 8: 内联引用样式 */
.markdown-body :deep(.src-ref) {
  color: #409eff;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85em;
}
.markdown-body :deep(.src-ref:hover) {
  color: #337ecc;
  text-decoration: underline;
}
.citation-popover {
  position: fixed;
  z-index: 9999;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  padding: 12px;
  max-width: 420px;
  min-width: 280px;
}
.citation-popover-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.citation-popover-text {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}

/* Phase 8 P1.3: 推荐问题 */
.follow-up-area {
  margin-top: 8px;
  padding: 8px 0;
}
.follow-up-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.follow-up-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
