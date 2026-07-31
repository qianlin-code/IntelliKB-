<template>
  <div class="qa-layout">
    <!-- 左侧：对话列表 -->
    <div class="qa-sidebar">
      <ConversationSidebar
        ref="sidebarRef"
        :kb-id="kbId"
        @select="onConversationSelect"
        @created="onConversationCreated"
      />
    </div>

    <!-- 右侧：主要区域 -->
    <div class="qa-main">
      <!-- 顶部信息 -->
      <div class="qa-header">
        <div class="header-left">
          <el-button text @click="$router.push('/kbs')">
            <el-icon><ArrowLeft /></el-icon> 返回
          </el-button>
          <span class="kb-label" v-if="kb">{{ kb.name }}</span>
          <!-- Phase 6: 模型提供商指示器 -->
          <el-tag
            v-if="llmProvider"
            size="small"
            :type="llmProvider === 'ollama' ? 'success' : ''"
            effect="plain"
            :title="`Provider: ${llmProvider}，Model: ${llmProviderModel || 'unknown'}`"
          >
            {{ llmProvider === 'ollama' ? '本地模型' : '云端模型' }}
            <span v-if="llmProviderModel" class="model-name">· {{ llmProviderModel }}</span>
          </el-tag>
        </div>
        <div class="header-right">
          <el-radio-group v-model="mode" size="small">
            <el-radio-button value="search">仅检索</el-radio-button>
            <el-radio-button value="ask">RAG 问答</el-radio-button>
            <el-radio-button value="agent">Agent 对话</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- 消息区域 -->
      <div class="message-area" ref="messageAreaRef">
        <!-- 对话消息（Phase 8: 轮次编号） -->
        <div v-if="storeMessages.length > 0" class="messages-list">
          <template v-for="(msg, idx) in storeMessages" :key="msg.id">
            <!-- Phase 8: 每轮开始显示轮次编号 -->
            <div v-if="msg.role === 'user' && getRoundNumber(idx) > 0" class="round-marker">
              第 {{ getRoundNumber(idx) }} 轮
            </div>
            <ChatMessage
              :role="msg.role"
              :content="msg.content"
              :msg-id="msg.id"
              :conv-id="store.currentConvId ?? undefined"
              :tool-calls="getToolCalls(msg)"
              :sources="getSources(msg)"
              :follow-up-questions="getFollowUps(msg)"
              @follow-up="onFollowUp"
              @regenerate="onRegenerate"
              @fork="onFork"
            />
          </template>
        </div>

        <!-- 非对话模式的显示 -->
        <div v-if="mode === 'search' && results.length > 0 && !searching">
          <div class="mode-results-header">
            检索结果 ({{ results.length }})
            <el-tooltip content="相似度基于向量余弦距离计算，范围 0-100%，低于系统阈值的结果已被过滤">
              <el-icon class="header-info-icon"><Info-Filled /></el-icon>
            </el-tooltip>
          </div>
          <el-card v-for="r in results" :key="r.chunk_id" class="result-card" shadow="hover">
            <div class="result-header">
              <span class="result-doc">
                <el-icon><Document /></el-icon>
                文档 #{{ r.document_id }}
              </span>
              <div class="result-score" :title="`相似度 ${Math.round(r.score * 100)}%，基于向量余弦距离`">
                <el-tag size="small" :type="scoreTagType(r.score)">{{ scoreLabel(r.score) }}</el-tag>
                <el-progress
                  :percentage="Math.round(r.score * 100)"
                  :color="scoreColor(r.score)"
                  :stroke-width="6"
                  style="width: 120px"
                />
              </div>
            </div>
            <div class="result-text">{{ r.content }}</div>
          </el-card>
        </div>

        <!-- 检索无结果提示 -->
        <div v-if="mode === 'search' && results.length === 0 && !searching && lastSearchQuestion" class="search-empty">
          <el-empty description="无法提供检索信息">
            <template #default>
              <div class="empty-hint">
                <p>当前知识库中未找到与“<strong>{{ lastSearchQuestion }}</strong>”相关的内容。</p>
                <p>请尝试更换关键词、简化查询，或向该知识库上传更多相关文档。</p>
              </div>
            </template>
          </el-empty>
        </div>

        <!-- Agent 流式渲染 -->
        <div v-if="agentStreaming" class="agent-stream-wrapper">
          <div class="message-avatar">
            <el-avatar :size="32" icon="ChatDotSquare" style="background: #67c23a" />
          </div>
          <div class="agent-stream-message">
            <div class="message-role-label">AI 助手</div>
            <AgentStreamRenderer ref="streamRendererRef" />
          </div>
        </div>

        <!-- RAG 流式渲染 -->
        <div v-if="ragStreaming" class="rag-stream-wrapper">
          <div class="message-avatar">
            <el-avatar :size="32" icon="ChatDotRound" style="background: #409eff" />
          </div>
          <div class="rag-stream-message">
            <div class="message-role-label">AI 助手</div>
            <StreamingText
              :key="ragStreamKey"
              url="/api/v1/qa/ask-stream"
              :body="ragStreamBody"
              @done="onRagStreamDone"
              @error="onRagStreamError"
            />
          </div>
        </div>

        <!-- 加载中 -->
        <div v-if="searching && mode !== 'agent'" class="loading-area">
          <el-skeleton :rows="4" animated />
        </div>

        <!-- 空状态 -->
        <el-empty
          v-if="storeMessages.length === 0 && !results.length && !searching && !agentStreaming && !ragStreaming"
          :description="emptyDescription"
        >
          <template #image>
            <el-icon :size="64" color="#c0c4cc"><ChatDotSquare /></el-icon>
          </template>
          <template #default>
            <div class="empty-hint">
              <p>{{ emptyHint }}</p>
              <el-button v-if="mode === 'agent' && !store.currentConvId" type="primary" size="small" @click="createConvForAgent">
                新建 Agent 对话
              </el-button>
            </div>
          </template>
        </el-empty>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          :placeholder="inputPlaceholder"
          @keydown.ctrl.enter="onSubmit"
          :disabled="agentStreaming || ragStreaming"
        />
        <div class="input-actions">
          <el-button
            type="primary"
            :loading="searching || agentStreaming || ragStreaming"
            :disabled="!question.trim()"
            @click="onSubmit"
          >
            <el-icon><Search /></el-icon> {{ submitLabel }}
          </el-button>
          <el-button v-if="agentStreaming" type="danger" @click="stopAgentStream">
            <el-icon><CircleClose /></el-icon> 停止
          </el-button>
          <el-button v-if="ragStreaming" type="danger" @click="stopRagStream">
            <el-icon><CircleClose /></el-icon> 停止
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Search, CircleClose, ChatDotSquare, InfoFilled, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getKBApi } from '@/api/knowledgeBase'
import { searchChunksApi, askQuestionApi, buildAskStreamPayload } from '@/api/qa'
import { agentChatApi, buildAgentStreamPayload, getLlmProviderInfo } from '@/api/agent'
import type { KnowledgeBase, SearchResult, ToolCallInfo, Message } from '@/types'
import { useConversationStore } from '@/store/conversation'
import { useSSE, SSEError } from '@/composables/useSSE'
import { useErrorHandler } from '@/composables/useErrorHandler'
import { useOnboarding } from '@/composables/useOnboarding'
import ChatMessage from '@/components/ChatMessage.vue'
import StreamingText from '@/components/StreamingText.vue'
// Phase 7: Agent 组件按需加载（仅 Agent 模式使用）
const ConversationSidebar = defineAsyncComponent(() => import('@/components/ConversationSidebar.vue'))
const AgentStreamRenderer = defineAsyncComponent(() => import('@/components/AgentStreamRenderer.vue'))

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.kbId)

const store = useConversationStore()
const { handle: handleError } = useErrorHandler()
const sidebarRef = ref<InstanceType<typeof ConversationSidebar> | null>(null)
const streamRendererRef = ref<InstanceType<typeof AgentStreamRenderer> | null>(null)
const messageAreaRef = ref<HTMLElement | null>(null)

// 模式
const mode = ref<'search' | 'ask' | 'agent'>('ask')
const question = ref('')
const searching = ref(false)
const kb = ref<KnowledgeBase | null>(null)

// 检索/问答结果
const results = ref<SearchResult[]>([])
const lastSearchQuestion = ref('')   // 记录最后一次搜索的问题，用于空状态提示
const answer = ref('')
const sources = ref<SearchResult[]>([])
const llmError = ref(false)

// Agent 流式
const agentStreaming = ref(false)
const llmProvider = ref('')          // Phase 6
const llmProviderModel = ref('')     // Phase 6
let abortController: AbortController | null = null
let agentAbortedByUser = false

// RAG 流式
const ragStreaming = ref(false)
const ragStreamKey = ref(0)
const ragStreamQuestion = ref('')
const ragStreamAnswer = ref('')
const ragStreamError = ref('')

// 从 store 获取消息
const storeMessages = computed(() => store.messages)

const inputPlaceholder = computed(() => {
  if (mode.value === 'search') return '输入关键词搜索，按 Ctrl+Enter 发送'
  if (mode.value === 'agent') return '向 Agent 提问，按 Ctrl+Enter 发送'
  return '输入问题，按 Ctrl+Enter 发送'
})

const submitLabel = computed(() => {
  if (agentStreaming.value || ragStreaming.value) return '生成中...'
  if (mode.value === 'search') return '搜索'
  if (mode.value === 'agent') return 'Agent 对话'
  return '提问'
})

const emptyDescription = computed(() => {
  if (mode.value === 'search') return '输入关键词开始检索知识库'
  if (mode.value === 'agent') return '选择或创建一个 Agent 对话'
  return '输入问题，开始 RAG 问答'
})

const emptyHint = computed(() => {
  if (mode.value === 'search') return '系统将返回与问题最相关的文本分块。'
  if (mode.value === 'agent') return 'Agent 会基于知识库进行多轮推理，并自动调用检索工具。'
  return 'AI 会基于检索到的文档内容生成带来源引用的回答。'
})

const ragStreamBody = computed(() =>
  buildAskStreamPayload({
    kb_id: kbId,
    question: ragStreamQuestion.value,
    top_k: 5,
    conversation_id: store.currentConvId,
  }),
)

// Phase 6: fetch LLM provider info
async function fetchProviderInfo() {
  try {
    const resp = await getLlmProviderInfo()
    llmProvider.value = resp.data?.provider || ''
    llmProviderModel.value = resp.data?.model || ''
  } catch { /* ignore */ }
}

const { startTour, hasCompleted } = useOnboarding()

onMounted(async () => {
  fetchProviderInfo()
  try {
    const resp = await getKBApi(kbId)
    kb.value = resp.data
    // 加载对话列表
    sidebarRef.value?.loadConversations()
    // 检查 URL 是否有 conv_id 参数
    const convId = route.query.conv_id ? Number(route.query.conv_id) : null
    if (convId) {
      store.setCurrentConv(convId)
      await store.loadMessages(convId)
    }
  } catch { /* handled */ }

  if (!hasCompleted('qa_page')) {
    setTimeout(() => {
      startTour({
        pageKey: 'qa_page',
        delay: 0,
        steps: [
          {
            element: '.qa-sidebar',
            popover: {
              title: '对话列表',
              description: '在这里新建、搜索、切换历史对话。',
              side: 'right',
            },
          },
          {
            element: '.header-right .el-radio-group',
            popover: {
              title: '问答模式',
              description: '仅检索：只看检索结果；RAG 问答：直接生成答案；Agent 对话：多轮推理与工具调用。',
              side: 'bottom',
            },
          },
          {
            element: '.message-area',
            popover: {
              title: '消息区域',
              description: '查看对话历史，悬停消息可编辑、重新生成或创建分支。',
              side: 'top',
            },
          },
          {
            element: '.input-area',
            popover: {
              title: '输入问题',
              description: '输入问题后按 Ctrl+Enter 发送。长问题已通过 POST body 传输，不受 URL 长度限制。',
              side: 'top',
            },
          },
        ],
      })
    }, 1000)
  }
})

// 监听模式切换：agent 模式下自动创建新对话
watch(mode, (newMode) => {
  if (newMode === 'agent' && !store.currentConvId) {
    createConvForAgent()
  }
})

async function createConvForAgent() {
  try {
    await store.createConversation(kbId)
  } catch { /* handled */ }
}

async function onSubmit() {
  if (!question.value.trim() || searching.value || agentStreaming.value) return

  if (mode.value === 'agent') {
    await doAgentChat()
  } else if (mode.value === 'search') {
    await doSearch()
  } else {
    await doAsk()
  }
}

async function doSearch() {
  searching.value = true
  results.value = []
  lastSearchQuestion.value = question.value
  answer.value = ''
  sources.value = []
  llmError.value = false

  try {
    const resp = await searchChunksApi({
      kb_id: kbId,
      question: question.value,
      top_k: 5,
    })
    results.value = resp.data.results
  } finally {
    searching.value = false
  }
}

async function doAsk() {
  if (!question.value.trim()) return

  // RAG 问答也纳入对话管理，确保有当前对话
  if (!store.currentConvId) {
    const conv = await store.createConversation(kbId)
    // 将当前对话 ID 同步到 URL，避免页面刷新/HMR 后状态丢失
    router.replace({ query: { ...route.query, conv_id: conv.id } })
  }

  const userQuestion = question.value
  question.value = ''
  store.appendUserMessage(userQuestion)
  scrollToBottom()

  // Phase P0: 优先使用 SSE 流式，失败回退到非流式
  try {
    await doAskStream(userQuestion)
    return
  } catch {
    // 流式失败，回退到非流式
  }

  searching.value = true
  results.value = []
  answer.value = ''
  sources.value = []
  llmError.value = false

  try {
    const resp = await askQuestionApi({
      kb_id: kbId,
      question: userQuestion,
      top_k: 5,
      conversation_id: store.currentConvId,
    })
    answer.value = resp.data.answer
    sources.value = resp.data.sources
    llmError.value = resp.data.llm_error ?? false
    store.appendAssistantMessage(resp.data.answer, undefined, resp.data.sources)
    scrollToBottom()
  } catch (err: any) {
    const { message } = handleError(err, 'RAG 问答')
    answer.value = message
    llmError.value = true
    store.appendAssistantMessage(message)
    scrollToBottom()
  } finally {
    searching.value = false
  }
}

async function doAskStream(userQuestion: string) {
  ragStreaming.value = true
  ragStreamQuestion.value = userQuestion
  ragStreamAnswer.value = ''
  ragStreamError.value = ''
  ragStreamKey.value++

  // StreamingText 组件自启动并在完成时触发回调
  return new Promise<void>((resolve, reject) => {
    const unwatchDone = watch(ragStreamAnswer, () => {
      // 由 onRagStreamDone 设置值，表示完成
      if (!ragStreaming.value) {
        unwatchDone()
        resolve()
      }
    })
    const unwatchError = watch(ragStreamError, (err) => {
      if (err) {
        unwatchDone()
        unwatchError()
        ragStreaming.value = false
        reject(new Error(err))
      }
    })
  })
}

function onRagStreamDone(text: string) {
  ragStreaming.value = false
  ragStreamAnswer.value = text
  answer.value = text
  // 流式结束后重新加载消息，确保 assistant 回复已持久化
  const convId = store.currentConvId
  if (convId) {
    store.loadMessages(convId).then(() => scrollToBottom())
  } else {
    store.appendAssistantMessage(text)
    scrollToBottom()
  }
}

function onRagStreamError(err: Error) {
  ragStreaming.value = false
  ragStreamError.value = err.message
  handleError(err, 'RAG 流式')
}

async function doAgentChat() {
  // 确保有对话
  if (!store.currentConvId) {
    const conv = await store.createConversation(kbId)
    router.replace({ query: { ...route.query, conv_id: conv.id } })
  }

  const userQuestion = question.value
  question.value = ''
  store.appendUserMessage(userQuestion)
  scrollToBottom()

  // 尝试流式对话
  const convId = store.currentConvId!
  try {
    await doAgentChatStream(userQuestion, convId)
    return
  } catch {
    // 流式失败，回退到非流式
  }

  // 非流式回退
  searching.value = true
  try {
    const resp = await agentChatApi({
      conversation_id: convId,
      kb_id: kbId,
      question: userQuestion,
      stream: false,
    })
    store.appendAssistantMessage(resp.data.answer, resp.data.tool_calls, resp.data.sources)
    scrollToBottom()
  } catch (err: any) {
    if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
      store.appendAssistantMessage('模型加载较慢，请稍后重试或切换到更快的模型。')
    } else {
      store.appendAssistantMessage('抱歉，Agent 对话处理出错，请稍后重试。')
    }
  } finally {
    searching.value = false
  }
}

async function doAgentChatStream(questionText: string, convId: number) {
  // 开始流式
  agentStreaming.value = true
  agentAbortedByUser = false
  streamRendererRef.value?.reset()
  abortController = new AbortController()

  try {
    const token = sessionStorage.getItem('access_token') || ''
    const url = '/api/v1/agent/chat-stream'
    const body = buildAgentStreamPayload(kbId, questionText, convId)

    // Phase P0: POST + JSON body，认证通过 access_token query param 传递
    const { stream } = useSSE(url, {
      signal: abortController.signal,
      method: 'POST',
      body,
      token,
    })

    for await (const { event, data } of stream()) {
      const shouldContinue = streamRendererRef.value?.handleEvent(event, data)
      if (shouldContinue === false) break
    }

    // 流式结束后从后端重新加载完整消息列表（包含已保存的 assistant 回复）
    // 否则 agentStreaming 置为 false 后 AgentStreamRenderer 消失，消息区会显示空白
    await store.loadMessages(convId)
    scrollToBottom()
  } catch (err: unknown) {
    if (err instanceof SSEError) {
      handleError(err, 'Agent 流式')
      if (err.status === 401) return
    } else if (err instanceof Error && err.name === 'AbortError' && agentAbortedByUser) {
      // 仅用户主动停止时忽略；其他情况继续抛出以触发非流式 fallback
      return
    } else {
      handleError(err, 'Agent 流式')
    }
    throw err // 让上层捕获回退到非流式
  } finally {
    agentStreaming.value = false
    abortController = null
  }
}

function stopAgentStream() {
  agentAbortedByUser = true
  abortController?.abort()
  agentStreaming.value = false
}

function stopRagStream() {
  // StreamingText 内部会在 unmounted 时 abort
  ragStreaming.value = false
}

function onConversationSelect(convId: number) {
  mode.value = 'agent'
  store.setCurrentConv(convId)
  store.loadMessages(convId)
  router.replace({ query: { ...route.query, conv_id: convId } })
}

function onConversationCreated(convId: number) {
  mode.value = 'agent'
  store.setCurrentConv(convId)
  store.messages = []
  router.replace({ query: { ...route.query, conv_id: convId } })
}

function getToolCalls(msg: Message): ToolCallInfo[] | undefined {
  const meta = msg.metadata_json
  if (meta && 'tool_calls_log' in meta) {
    return meta.tool_calls_log as ToolCallInfo[]
  }
  // 向后兼容 Phase 3 的 tool_calls 字段名
  if (meta && 'tool_calls' in meta) {
    return meta.tool_calls as ToolCallInfo[]
  }
  return undefined
}

function getSources(msg: Message): SearchResult[] | undefined {
  const meta = msg.metadata_json
  if (meta && 'sources' in meta) {
    return meta.sources as SearchResult[]
  }
  return undefined
}

function scrollToBottom() {
  nextTick(() => {
    if (messageAreaRef.value) {
      messageAreaRef.value.scrollTop = messageAreaRef.value.scrollHeight
    }
  })
}

function scoreColor(score: number) {
  if (score >= 0.75) return '#67c23a'
  if (score >= 0.55) return '#e6a23c'
  return '#f56c6c'
}

function scoreTagType(score: number): 'success' | 'warning' | 'danger' {
  if (score >= 0.75) return 'success'
  if (score >= 0.55) return 'warning'
  return 'danger'
}

function scoreLabel(score: number): string {
  if (score >= 0.75) return '高度相关'
  if (score >= 0.55) return '相关'
  return '弱相关'
}

// Phase 8: 多轮对话轮次编号
function getRoundNumber(msgIdx: number): number {
  let round = 0
  const msgs = storeMessages.value
  for (let i = 0; i <= msgIdx; i++) {
    if (msgs[i]?.role === 'user') round++
  }
  return round
}

// Phase 8: 点击历史消息重新追问
function onReask(msg: any) {
  if (msg.role === 'user') {
    question.value = msg.content
  }
}

// Phase 8 P1.3: 获取推荐问题
function getFollowUps(msg: any): string[] | undefined {
  const meta = msg.metadata_json
  if (meta && 'follow_up_questions' in meta) {
    return meta.follow_up_questions as string[]
  }
  return undefined
}

// Phase 8 P1.3: 点击推荐问题 → 自动填入并发送
function onFollowUp(q: string) {
  question.value = q
  onSubmit()
}

// Phase P0: 重新生成回答
async function onRegenerate(msgId: number, editedQuestion: string) {
  const convId = store.currentConvId
  if (!convId) return
  searching.value = true
  try {
    await store.regenerateMessage(convId, msgId, editedQuestion)
    ElMessage.success('已重新生成')
    scrollToBottom()
  } catch (err: any) {
    handleError(err, '重新生成')
  } finally {
    searching.value = false
  }
}

// Phase P0: 从指定消息分叉对话
async function onFork(msgId: number) {
  const convId = store.currentConvId
  if (!convId) return
  searching.value = true
  try {
    await store.forkConversation(convId, msgId)
    ElMessage.success('已创建分支对话')
    scrollToBottom()
  } catch (err: any) {
    handleError(err, '分叉对话')
  } finally {
    searching.value = false
  }
}
</script>

<style scoped>
.qa-layout {
  display: flex;
  height: calc(100vh - 60px);
  overflow: hidden;
}
.qa-sidebar {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid #e4e7ed;
}
.qa-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.qa-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kb-label {
  font-weight: 600;
  color: #409eff;
}
.model-name {
  margin-left: 2px;
  font-weight: 500;
}
.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}
.messages-list {
  max-width: 800px;
  margin: 0 auto;
}
/* Phase 8: 轮次标记 */
.round-marker {
  text-align: center;
  font-size: 12px;
  color: #909399;
  margin: 16px 0 8px;
  position: relative;
}
.round-marker::before,
.round-marker::after {
  content: '';
  display: inline-block;
  width: 40px;
  height: 1px;
  background: #dcdfe6;
  vertical-align: middle;
  margin: 0 8px;
}
.mode-results-header {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
}
.header-info-icon {
  color: #909399;
  cursor: help;
  font-size: 14px;
}
.result-card {
  margin-bottom: 12px;
  max-width: 800px;
  margin-left: auto;
  margin-right: auto;
}
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 12px;
}
.result-doc {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #606266;
  font-size: 13px;
}
.result-score {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.result-text {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.6;
  color: #303133;
}
.search-empty {
  max-width: 800px;
  margin: 24px auto;
}
.agent-stream-wrapper,
.rag-stream-wrapper {
  display: flex;
  gap: 12px;
  padding: 16px 0;
  max-width: 800px;
  margin: 0 auto;
}
.agent-stream-message,
.rag-stream-message {
  max-width: 75%;
  background: #f0f9eb;
  padding: 12px 16px;
  border-radius: 8px;
  flex: 1;
}
.rag-stream-message {
  background: #f5faff;
}
.message-role-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.loading-area {
  max-width: 800px;
  margin: 24px auto;
}
.input-area {
  padding: 12px 24px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}
.input-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.empty-hint {
  text-align: center;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.empty-hint p {
  margin: 0 0 12px;
}
</style>
