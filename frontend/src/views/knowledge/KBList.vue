<template>
  <div class="kb-list-page">
    <div class="page-header">
      <h2>知识库管理</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> 创建知识库
      </el-button>
    </div>

    <!-- 空状态 -->
    <el-empty v-if="!loading && kbStore.kbList.length === 0" description="暂无知识库，点击上方按钮创建" />

    <!-- 卡片网格 -->
    <el-row v-else :gutter="20">
      <el-col v-for="kb in kbStore.kbList" :key="kb.id" :xs="24" :sm="12" :md="8" :lg="6">
        <el-card class="kb-card" shadow="hover" @click="goDetail(kb.id)">
          <template #header>
            <div class="kb-card-header">
              <span class="kb-name">{{ kb.name }}</span>
              <el-tag :type="kb.is_public ? 'success' : 'info'" size="small">
                {{ kb.is_public ? '公开' : '私有' }}
              </el-tag>
            </div>
          </template>
          <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
          <div class="kb-meta">
            <span>分块: {{ kb.chunk_size }} / {{ kb.chunk_overlap }}</span>
          </div>
          <div class="kb-actions" @click.stop>
            <el-button size="small" type="primary" plain @click="goQA(kb.id)">
              进入问答
            </el-button>
            <el-button size="small" @click="goDetail(kb.id)">管理</el-button>
            <el-popconfirm title="确认删除该知识库？所有文档将被清理。" @confirm="onDelete(kb.id)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 创建对话框 -->
    <el-dialog v-model="showCreateDialog" title="创建知识库" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="200" placeholder="输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选描述" />
        </el-form-item>
        <el-form-item label="公开">
          <el-switch v-model="form.is_public" />
          <span class="form-hint">公开后其他用户可检索</span>
        </el-form-item>
        <el-form-item label="分块大小">
          <el-input-number v-model="form.chunk_size" :min="100" :max="2000" :step="50" />
        </el-form-item>
        <el-form-item label="分块重叠">
          <el-input-number v-model="form.chunk_overlap" :min="0" :max="500" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useKBStore } from '@/store/knowledgeBase'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useOnboarding } from '@/composables/useOnboarding'

const router = useRouter()
const kbStore = useKBStore()

const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  description: '',
  is_public: false,
  chunk_size: 500,
  chunk_overlap: 50,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
}

async function onCreate() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  creating.value = true
  try {
    await kbStore.createKB({ ...form })
    showCreateDialog.value = false
    form.name = ''
    form.description = ''
  } catch {
    // error handled by interceptor
  } finally {
    creating.value = false
  }
}

function goDetail(kbId: number) {
  router.push(`/kbs/${kbId}`)
}

function goQA(kbId: number) {
  router.push(`/qa/${kbId}`)
}

async function onDelete(kbId: number) {
  await kbStore.removeKB(kbId)
}

const { startTour, hasCompleted } = useOnboarding()

onMounted(() => {
  if (!hasCompleted('kb_list')) {
    startTour({
      pageKey: 'kb_list',
      delay: 600,
      steps: [
        {
          element: '.page-header h2',
          popover: {
            title: '知识库管理',
            description: '在这里创建、查看和删除知识库。每个知识库对应一个独立的知识领域。',
            side: 'bottom',
          },
        },
        {
          element: '.page-header .el-button',
          popover: {
            title: '创建知识库',
            description: '点击创建你的第一个知识库，设置名称、描述、分块策略等。',
            side: 'bottom',
          },
        },
        {
          element: '.kb-card',
          popover: {
            title: '知识库卡片',
            description: '点击卡片进入详情页，可上传文档、配置 Agent 人设、查看统计。',
            side: 'top',
          },
        },
        {
          element: '.kb-actions',
          popover: {
            title: '快捷操作',
            description: '直接进入问答，或管理、删除知识库。',
            side: 'top',
          },
        },
      ],
    })
  }
})
</script>

<style scoped>
.kb-list-page { max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { margin: 0; font-size: 20px; }

.kb-card { cursor: pointer; margin-bottom: 20px; }
.kb-card:hover { border-color: #409eff; }
.kb-card-header { display: flex; justify-content: space-between; align-items: center; }
.kb-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-desc { color: #909399; font-size: 13px; min-height: 36px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-meta { color: #c0c4cc; font-size: 12px; margin: 8px 0; }
.kb-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.form-hint { margin-left: 8px; color: #909399; font-size: 12px; }
</style>
