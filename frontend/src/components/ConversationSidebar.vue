<template>
  <div class="conversation-sidebar">
    <div class="sidebar-header">
      <span class="sidebar-title">对话列表</span>
    </div>

    <!-- Phase 9: 搜索框 + 筛选（debounce 300ms 后端搜索） -->
    <div class="sidebar-search">
      <el-input
        v-model="searchQuery"
        placeholder="搜索标题或消息内容..."
        :prefix-icon="Search"
        clearable
        size="small"
        @input="onSearchInput"
      />
    </div>
    <!-- Phase 9: 时间范围筛选 -->
    <div class="sidebar-filters" v-if="showFilters">
      <el-date-picker
        v-model="filterDates"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        style="width: 100%"
        @change="onFilterChange"
      />
    </div>

    <div class="sidebar-actions">
      <el-button
        type="primary"
        size="small"
        style="width: 100%"
        :icon="Plus"
        @click="handleNew"
      >
        新建对话
      </el-button>
    </div>

    <div class="sidebar-list" v-loading="loading">
      <div
        v-for="conv in filteredConversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === currentId }"
        @click="handleSelect(conv.id)"
      >
        <div class="conv-title">
          <el-icon :size="14"><ChatDotSquare /></el-icon>
          <!-- Phase 9: 置顶/收藏标记 -->
          <el-icon v-if="conv.is_pinned" :size="12" style="color:#e6a23c"><StarFilled /></el-icon>
          <el-icon v-if="conv.is_starred && !conv.is_pinned" :size="12" style="color:#409eff"><StarFilled /></el-icon>
          <span class="conv-title-text">{{ conv.title || '新对话' }}</span>
        </div>
        <div class="conv-actions">
          <!-- Phase 9: 置顶按钮 -->
          <el-button
            text size="small"
            :icon="conv.is_pinned ? 'StarFilled' : 'Star'"
            :style="{ color: conv.is_pinned ? '#e6a23c' : '' }"
            @click.stop="handlePin(conv)"
            :title="conv.is_pinned ? '取消置顶' : '置顶'"
          />
          <!-- Phase 9: 导出按钮（下拉格式选择） -->
          <el-dropdown trigger="click" @command="(fmt: string) => handleExport(conv, fmt)">
            <el-button text size="small" :icon="Download" @click.stop title="导出对话" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="md">导出 Markdown</el-dropdown-item>
                <el-dropdown-item command="pdf" disabled>导出 PDF (即将支持)</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            text
            size="small"
            :icon="Edit"
            @click.stop="handleRename(conv)"
          />
          <el-button
            text
            size="small"
            type="danger"
            :icon="Delete"
            @click.stop="handleDelete(conv.id)"
          />
        </div>
      </div>

      <el-empty v-if="filteredConversations.length === 0 && !loading" description="暂无对话" :image-size="60" />
    </div>

    <!-- 重命名对话框 -->
    <el-dialog v-model="renameVisible" title="重命名对话" width="360px" :close-on-click-modal="false">
      <el-input v-model="renameTitle" placeholder="输入新标题" maxlength="200" />
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" @click="handleRenameConfirm">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Plus, ChatDotSquare, Edit, Delete, Search, Download, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { Conversation, Message } from '@/types'
import { useConversationStore } from '@/store/conversation'
import { downloadConversation } from '@/api/conversation'

const props = defineProps<{
  kbId: number
}>()

const emit = defineEmits<{
  select: [convId: number]
  created: [convId: number]
}>()

const store = useConversationStore()
const loading = ref(false)
const renameVisible = ref(false)
const renameTarget = ref<Conversation | null>(null)
const renameTitle = ref('')

// Phase 4+9: 搜索（debounce 300ms 后端搜索）
const searchQuery = ref('')
const filterDates = ref<[Date, Date] | null>(null)
const showFilters = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

const conversations = computed(() => store.conversations)
const currentId = store.currentConvId

const filteredConversations = computed(() => conversations.value)

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadConversations()
  }, 300)
}

function onFilterChange() {
  loadConversations()
}

async function loadConversations() {
  loading.value = true
  try {
    let startDate: string | undefined
    let endDate: string | undefined
    if (filterDates.value) {
      startDate = filterDates.value[0]?.toISOString()
      endDate = filterDates.value[1]?.toISOString()
    }
    await store.loadConversations(
      props.kbId,
      1, 50,
      searchQuery.value || undefined,
      startDate,
      endDate,
    )
  } finally {
    loading.value = false
  }
}

async function handleNew() {
  try {
    const conv = await store.createConversation(props.kbId)
    emit('created', conv.id)
  } catch {
    // handled
  }
}

function handleSelect(convId: number) {
  store.setCurrentConv(convId)
  store.loadMessages(convId)
  emit('select', convId)
}

async function handleDelete(convId: number) {
  await store.deleteConversation(convId)
}

async function handlePin(conv: Conversation) {
  await store.pinConversation(conv.id, !conv.is_pinned)
}

function handleRename(conv: Conversation) {
  renameTarget.value = conv
  renameTitle.value = conv.title || ''
  renameVisible.value = true
}

async function handleRenameConfirm() {
  if (renameTarget.value && renameTitle.value.trim()) {
    await store.updateTitle(renameTarget.value.id, renameTitle.value.trim())
  }
  renameVisible.value = false
}

// Phase 9: 后端驱动的对话导出
async function handleExport(conv: Conversation, format: string = 'md') {
  try {
    await downloadConversation(conv.id, format as 'md' | 'pdf', conv.title || 'conversation')
    ElMessage.success('导出成功')
  } catch {
    // 后端不可用时回退到客户端导出
    let messages: Message[] = store.messages
    if (conv.id !== store.currentConvId) {
      await store.loadMessages(conv.id)
      messages = store.messages
    }
    if (messages.length === 0) {
      ElMessage.warning('该对话暂无消息可导出')
      return
    }
    let md = `# ${conv.title || '对话'}\n\n`
    md += `> ${conv.created_at}\n\n---\n\n`
    for (const m of messages) {
      md += `### ${m.role === 'user' ? '👤 User' : '🤖 Assistant'}\n\n`
      md += m.content + '\n\n'
      const meta = m.metadata_json as any
      if (meta?.sources?.length) {
        md += '> **参考来源:**\n'
        meta.sources.forEach((s: any, i: number) => {
          md += `> [${i+1}] 文档#${s.document_id} — ${(s.content||'').slice(0,100)}\n`
        })
        md += '\n'
      }
    }
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${conv.title || 'conversation'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }
}

onMounted(() => {
  loadConversations()
})

defineExpose({ loadConversations })
</script>

<style scoped>
.conversation-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #e4e7ed;
}
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #ebeef5;
}
.sidebar-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}
.sidebar-search {
  padding: 8px 12px 0;
}
.sidebar-filters {
  padding: 4px 12px 0;
}
.sidebar-actions {
  padding: 12px;
}
.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 0.2s;
}
.conv-item:hover {
  background: #f5f7fa;
}
.conv-item.active {
  background: #ecf5ff;
}
.conv-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.conv-title-text {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
}
.conv-actions {
  display: none;
  gap: 2px;
  flex-shrink: 0;
}
.conv-item:hover .conv-actions {
  display: flex;
}
</style>
