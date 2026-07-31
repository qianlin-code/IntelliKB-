<template>
  <div class="kb-detail-page">
    <div class="page-header">
      <el-button text @click="$router.push('/kbs')">
        <el-icon><ArrowLeft /></el-icon> 返回列表
      </el-button>
    </div>

    <!-- 加载中 -->
    <el-skeleton v-if="loading" :rows="4" animated />

    <template v-else-if="kb">
      <!-- KB 信息卡片 -->
      <el-card class="kb-info-card">
        <template #header>
          <div class="kb-info-header">
            <span class="kb-title">{{ kb.name }}</span>
            <div class="kb-info-actions">
              <el-tag :type="kb.is_public ? 'success' : 'info'" size="small">
                {{ kb.is_public ? '公开' : '私有' }}
              </el-tag>
              <el-button size="small" type="primary" @click="$router.push(`/qa/${kb.id}`)">
                进入问答
              </el-button>
              <el-button size="small" @click="openEdit">编辑</el-button>
              <el-popconfirm title="确认删除该知识库？" @confirm="onDeleteKB">
                <template #reference>
                  <el-button size="small" type="danger" plain>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
        </template>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-meta-row">
          <span>分块大小: {{ kb.chunk_size }}</span>
          <span>分块重叠: {{ kb.chunk_overlap }}</span>
          <span>模型: {{ kb.embedding_model }}</span>
          <span>创建: {{ kb.created_at?.slice(0, 10) }}</span>
        </div>
      </el-card>

      <!-- Phase P0: KB 统计 + Agent 人设 -->
      <el-row :gutter="20" class="stats-agent-row">
        <el-col :span="12">
          <el-card class="stats-card">
            <template #header>
              <div class="card-header">知识库统计</div>
            </template>
            <el-row :gutter="16">
              <el-col :span="8">
                <div class="stat-item">
                  <div class="stat-value">{{ stats?.document_count ?? 0 }}</div>
                  <div class="stat-label">文档数</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="stat-item">
                  <div class="stat-value">{{ stats?.chunk_count ?? 0 }}</div>
                  <div class="stat-label">分块数</div>
                </div>
              </el-col>
              <el-col :span="8">
                <div class="stat-item">
                  <div class="stat-value">{{ formatSize(stats?.total_size_bytes ?? 0) }}</div>
                  <div class="stat-label">总大小</div>
                </div>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card class="agent-card">
            <template #header>
              <div class="card-header">
                <span>Agent 人设</span>
                <el-button size="small" text @click="openAgentConfig">配置</el-button>
              </div>
            </template>
            <div class="agent-prompt-preview">
              {{ agentPrompt || '使用默认系统提示词，点击右上角配置自定义人设。' }}
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 文档管理 -->
      <el-card class="doc-section">
        <template #header>
          <div class="doc-header">
            <span>文档列表 ({{ totalDocs }})</span>
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              accept=".pdf,.docx,.md,.txt"
              :on-change="onFileChange"
            >
              <el-button type="primary" size="small" :loading="uploading">
                <el-icon><Upload /></el-icon> 上传文档
              </el-button>
            </el-upload>
          </div>
        </template>

        <el-empty v-if="docs.length === 0 && !uploading" description="暂无文档，点击上方按钮上传" />

        <el-table v-else :data="docs" stripe style="width: 100%">
          <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column prop="file_type" label="类型" width="70" />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">
              {{ formatSize(row.file_size) }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="chunk_count" label="分块数" width="80" />
          <el-table-column label="时间" width="110">
            <template #default="{ row }">{{ row.created_at?.slice(0, 10) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text @click="viewChunks(row)">查看分块</el-button>
              <el-popconfirm title="确认删除？" @confirm="onDeleteDoc(row.id)">
                <template #reference>
                  <el-button size="small" type="danger" text>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 成员管理 -->
      <el-card class="member-section">
        <MemberManager :kb-id="kbId" :is-owner="true" />
      </el-card>
    </template>

    <!-- 编辑对话框 -->
    <el-dialog v-model="showEditDialog" title="编辑知识库" width="500px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="editForm.name" maxlength="200" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="公开">
          <el-switch v-model="editForm.is_public" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onUpdateKB">保存</el-button>
      </template>
    </el-dialog>

    <!-- Phase P0: Agent 人设配置对话框 -->
    <el-dialog v-model="showAgentConfigDialog" title="配置 Agent 人设" width="600px">
      <el-form label-width="100px">
        <el-form-item label="系统提示词">
          <el-input
            v-model="agentConfigForm.system_prompt"
            type="textarea"
            :rows="8"
            maxlength="2000"
            show-word-limit
            placeholder="输入自定义系统提示词，将覆盖默认人设。留空则恢复默认。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAgentConfigDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingAgentConfig" @click="onUpdateAgentConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- Phase P0: 文档分块查看对话框 -->
    <el-dialog v-model="showChunksDialog" :title="`文档分块 - ${chunkDocName}`" width="700px" top="8vh">
      <div v-loading="chunksLoading" class="chunks-container">
        <el-empty v-if="!chunksLoading && chunks.length === 0" description="暂无分块" />
        <div v-for="(chunk, idx) in chunks" :key="chunk.id" class="chunk-item">
          <div class="chunk-header">
            <el-tag size="small" type="info">#{{ chunk.chunk_index }}</el-tag>
            <span class="chunk-tokens">{{ chunk.token_count }} tokens</span>
          </div>
          <div class="chunk-content">{{ chunk.content }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Upload } from '@element-plus/icons-vue'
import { useKBStore } from '@/store/knowledgeBase'
import { getKBApi, updateKBApi, deleteKBApi, getKBStatsApi, updateAgentConfigApi } from '@/api/knowledgeBase'
import { uploadDocumentApi, listDocumentsApi, deleteDocumentApi, getChunksApi } from '@/api/document'
import MemberManager from '@/components/MemberManager.vue'
import { ElMessage } from 'element-plus'
import type { KnowledgeBase, DocumentInfo, KBUpdate, KBStats, ChunkInfo } from '@/types'
import { useOnboarding } from '@/composables/useOnboarding'

const route = useRoute()
const router = useRouter()
const kbStore = useKBStore()

const kbId = Number(route.params.kbId)
const loading = ref(true)
const uploading = ref(false)
const saving = ref(false)
const kb = ref<KnowledgeBase | null>(null)
const docs = ref<DocumentInfo[]>([])
const totalDocs = ref(0)
const stats = ref<KBStats | null>(null)
const agentPrompt = ref('')

const showEditDialog = ref(false)
const editForm = reactive<KBUpdate>({ name: '', description: '', is_public: false })

const showAgentConfigDialog = ref(false)
const savingAgentConfig = ref(false)
const agentConfigForm = reactive<{ system_prompt: string }>({ system_prompt: '' })

const showChunksDialog = ref(false)
const chunksLoading = ref(false)
const chunkDocName = ref('')
const chunks = ref<ChunkInfo[]>([])

async function load() {
  loading.value = true
  try {
    const [kbResp, docResp, statsResp] = await Promise.all([
      getKBApi(kbId),
      listDocumentsApi(kbId),
      getKBStatsApi(kbId).catch(() => ({ data: null })),
    ])
    kb.value = kbResp.data
    docs.value = docResp.data.items
    totalDocs.value = docResp.data.total
    stats.value = statsResp.data
    agentPrompt.value = (kb.value as any)?.system_prompt || ''
  } catch {
    router.push('/kbs')
  } finally {
    loading.value = false
  }
}

function openEdit() {
  if (!kb.value) return
  editForm.name = kb.value.name
  editForm.description = kb.value.description || ''
  editForm.is_public = kb.value.is_public
  showEditDialog.value = true
}

function openAgentConfig() {
  agentConfigForm.system_prompt = agentPrompt.value
  showAgentConfigDialog.value = true
}

async function onUpdateKB() {
  saving.value = true
  try {
    const resp = await updateKBApi(kbId, editForm)
    kb.value = resp.data
    showEditDialog.value = false
    ElMessage.success('已更新')
  } finally {
    saving.value = false
  }
}

async function onUpdateAgentConfig() {
  savingAgentConfig.value = true
  try {
    const resp = await updateAgentConfigApi(kbId, agentConfigForm.system_prompt)
    agentPrompt.value = resp.data.system_prompt || ''
    showAgentConfigDialog.value = false
    ElMessage.success('Agent 人设已更新')
  } finally {
    savingAgentConfig.value = false
  }
}

async function onDeleteKB() {
  await deleteKBApi(kbId)
  ElMessage.success('知识库已删除')
  router.push('/kbs')
}

async function onFileChange(file: any) {
  uploading.value = true
  try {
    await uploadDocumentApi(kbId, file.raw)
    ElMessage.success('文档上传成功')
    await load()
  } finally {
    uploading.value = false
  }
}

async function onDeleteDoc(docId: number) {
  await deleteDocumentApi(docId)
  ElMessage.success('文档已删除')
  await load()
}

async function viewChunks(doc: DocumentInfo) {
  chunkDocName.value = doc.filename
  showChunksDialog.value = true
  chunksLoading.value = true
  try {
    const resp = await getChunksApi(doc.id)
    chunks.value = resp.data.chunks
  } finally {
    chunksLoading.value = false
  }
}

function statusType(status: string) {
  const map: Record<string, string> = {
    done: 'success', error: 'danger',
    uploading: 'warning', parsing: 'warning', chunking: 'warning', indexing: 'warning',
  }
  return map[status] || 'info'
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const { startTour, hasCompleted } = useOnboarding()

onMounted(() => {
  load()
  if (!hasCompleted('kb_detail')) {
    setTimeout(() => {
      startTour({
        pageKey: 'kb_detail',
        delay: 0,
        steps: [
          {
            element: '.kb-info-card',
            popover: {
              title: '知识库详情',
              description: '查看知识库基本信息，点击"进入问答"可立即开始对话。',
              side: 'bottom',
            },
          },
          {
            element: '.stats-agent-row',
            popover: {
              title: '统计与人设',
              description: '查看文档/分块/存储统计，并配置 Agent 系统提示词以定制回答风格。',
              side: 'bottom',
            },
          },
          {
            element: '.doc-section',
            popover: {
              title: '文档管理',
              description: '上传 PDF / DOCX / MD / TXT 文档，后台自动解析并向量化。',
              side: 'top',
            },
          },
          {
            element: '.doc-section .el-button',
            popover: {
              title: '上传文档',
              description: '至少上传一个文档后，才能使用问答与 Agent 功能。',
              side: 'top',
            },
          },
          {
            element: '.member-section',
            popover: {
              title: '成员管理',
              description: '邀请其他用户协作，设置只读或编辑权限。',
              side: 'top',
            },
          },
        ],
      })
    }, 800)
  }
})
</script>

<style scoped>
.kb-detail-page { max-width: 1200px; margin: 0 auto; }
.page-header { margin-bottom: 16px; }
.kb-info-card { margin-bottom: 20px; }
.kb-info-header { display: flex; justify-content: space-between; align-items: center; }
.kb-info-actions { display: flex; gap: 8px; align-items: center; }
.kb-title { font-size: 18px; font-weight: 600; }
.kb-desc { color: #606266; margin: 8px 0; }
.kb-meta-row { display: flex; gap: 24px; color: #909399; font-size: 13px; }

.stats-agent-row { margin-bottom: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.stat-item { text-align: center; padding: 8px 0; }
.stat-value { font-size: 24px; font-weight: bold; color: #409eff; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.agent-prompt-preview {
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.doc-section { margin-bottom: 20px; }
.doc-header { display: flex; justify-content: space-between; align-items: center; }

.chunks-container { max-height: 60vh; overflow-y: auto; }
.chunk-item {
  margin-bottom: 12px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}
.chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.chunk-tokens { font-size: 12px; color: #909399; }
.chunk-content {
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
