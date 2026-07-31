<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/store/user'
import { generateApiKeyApi, revokeApiKeyApi, getApiKeyInfoApi } from '@/api/auth'
import { useOnboarding } from '@/composables/useOnboarding'

const router = useRouter()
const userStore = useUserStore()

const apiKeyPrefix = ref<string | null>(null)
const apiKeyExpires = ref<string | null>(null)
const apiKeyLastUsed = ref<string | null>(null)
const apiKeyEnabled = ref(false)
const apiKeyDetailVisible = ref(false)

async function loadApiKeyInfo() {
  try {
    const resp = await getApiKeyInfoApi()
    apiKeyPrefix.value = resp.data.prefix
    apiKeyExpires.value = resp.data.expires_at
    apiKeyLastUsed.value = resp.data.last_used_at
    apiKeyEnabled.value = resp.data.enabled
  } catch {
    apiKeyEnabled.value = false
  }
}

function showApiKeyDetail() {
  apiKeyDetailVisible.value = true
}

async function handleGenerateApiKey() {
  try {
    const resp = await generateApiKeyApi()
    ElMessageBox.alert(
      `API Key 已生成，请立即保存：<br><code style="word-break:break-all;user-select:all">${resp.data.api_key}</code>`,
      'API Key',
      { dangerouslyUseHTMLString: true, type: 'success' },
    )
    await loadApiKeyInfo()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '生成失败')
  }
}

async function handleRevokeApiKey() {
  try {
    await ElMessageBox.confirm('确定要吊销 API Key 吗？吊销后所有使用该 Key 的外部调用将立即失效。', '确认吊销', {
      type: 'warning',
    })
    await revokeApiKeyApi()
    ElMessage.success('API Key 已吊销')
    await loadApiKeyInfo()
  } catch {
    // 用户取消
  }
}

const { startTour, hasCompleted } = useOnboarding()

onMounted(() => {
  loadApiKeyInfo()
  if (!hasCompleted('dashboard')) {
    startTour({
      pageKey: 'dashboard',
      delay: 800,
      steps: [
        {
          element: '.logo',
          popover: {
            title: '欢迎来到 IntelliKB',
            description: '基于 RAG + ReAct Agent 的企业级智能知识库平台，支持文档解析、混合检索与 Agent 对话。',
            side: 'bottom',
          },
        },
        {
          element: '.header-nav',
          popover: {
            title: '顶部导航',
            description: '在工作台与知识库管理之间快速切换。',
            side: 'bottom',
          },
        },
        {
          element: '.el-col:nth-child(1) .el-card',
          popover: {
            title: '快速入口',
            description: '从这里进入知识库管理或开始智能问答。',
            side: 'right',
          },
        },
        {
          element: '.el-col:nth-child(2) .el-card',
          popover: {
            title: 'API Key 管理',
            description: '生成 API Key 后可通过外部系统调用 IntelliKB 接口。',
            side: 'left',
          },
        },
      ],
    })
  }
})
</script>

<template>
  <div class="dashboard-container">
    <h2>工作台</h2>

    <el-row :gutter="20">
      <!-- 欢迎卡片 -->
      <el-col :span="14">
        <el-card>
          <template #header>
            <span>欢迎使用 IntelliKB</span>
          </template>
          <p>欢迎回来，{{ userStore.username }}！</p>
          <p style="color: #909399; margin-top: 8px">
            IntelliKB 是基于 RAG + ReAct Agent 的企业级智能知识库平台，
            支持多格式文档解析、混合检索问答、Agent 自主推理。
          </p>
          <div style="margin-top: 16px; display: flex; gap: 12px">
            <el-button type="primary" @click="router.push('/kbs')">
              📄 知识库管理
            </el-button>
            <el-button type="success" @click="router.push('/kbs')">
              🔍 智能问答
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- API Key 管理卡片 -->
      <el-col :span="10">
        <el-card>
          <template #header>
            <span>API Key 管理</span>
          </template>
          <div v-if="apiKeyEnabled && apiKeyPrefix" class="api-key-info">
            <p><strong>前缀：</strong><code>{{ apiKeyPrefix }}</code></p>
            <p v-if="apiKeyExpires"><strong>过期时间：</strong>{{ new Date(apiKeyExpires).toLocaleString() }}</p>
            <div style="margin-top: 12px">
              <el-button type="primary" size="small" @click="showApiKeyDetail">查看详情</el-button>
              <el-button type="primary" size="small" @click="handleGenerateApiKey">重新生成</el-button>
              <el-button type="danger" size="small" @click="handleRevokeApiKey">吊销</el-button>
            </div>
          </div>
          <div v-else>
            <p style="color: #909399; margin-bottom: 12px">尚未生成 API Key</p>
            <el-button type="primary" @click="handleGenerateApiKey">生成 API Key</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- API Key 详情弹窗 -->
    <el-dialog v-model="apiKeyDetailVisible" title="API Key 详情" width="420px">
      <div class="api-key-detail">
        <p><strong>前缀：</strong><code>{{ apiKeyPrefix }}</code></p>
        <p><strong>状态：</strong><el-tag type="success">有效</el-tag></p>
        <p v-if="apiKeyExpires"><strong>过期时间：</strong>{{ new Date(apiKeyExpires).toLocaleString() }}</p>
        <p v-else><strong>过期时间：</strong>永久有效</p>
        <p v-if="apiKeyLastUsed"><strong>最后使用：</strong>{{ new Date(apiKeyLastUsed).toLocaleString() }}</p>
        <p v-else><strong>最后使用：</strong>从未使用</p>
        <p style="color: #909399; margin-top: 12px; font-size: 12px">
          安全提示：完整的 API Key 仅在生成时显示一次，此处不再展示。
        </p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard-container h2 {
  font-size: 20px;
  margin: 0 0 20px;
}
.api-key-info code {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.api-key-detail p {
  margin: 8px 0;
}
.api-key-detail code {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
</style>
