<template>
  <div class="admin-stats">
    <h3>系统统计</h3>
    <el-row :gutter="16" class="stats-cards">
      <el-col :span="6">
        <el-card shadow="hover"><template #header>用户数</template>
          <div class="stat-value">{{ stats.user_count ?? '...' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover"><template #header>知识库数</template>
          <div class="stat-value">{{ stats.kb_count ?? '...' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover"><template #header>文档数</template>
          <div class="stat-value">{{ stats.document_count ?? '...' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover"><template #header>会话数</template>
          <div class="stat-value">{{ stats.conversation_count ?? '...' }}</div>
        </el-card>
      </el-col>
    </el-row>
    <el-card class="info-card" shadow="hover" style="margin-top:16px">
      <template #header>环境信息</template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="LLM Provider">{{ stats.llm_provider ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="App 版本">{{ stats.app_version ?? '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- Phase P0: 云端 LLM 成本统计 -->
    <el-card class="cost-card" shadow="hover" style="margin-top:16px">
      <template #header>
        <span>云端 LLM 成本统计</span>
        <el-tag size="small" type="info" style="margin-left:8px">{{ costStats.provider ?? '-' }}</el-tag>
      </template>
      <el-row :gutter="16">
        <el-col :span="12">
          <div class="cost-section">
            <div class="cost-title">今日消耗</div>
            <el-progress
              :percentage="dailyPercent"
              :status="dailyPercent >= 90 ? 'exception' : ''"
              :stroke-width="18"
              :show-text="true"
            />
            <div class="cost-detail">
              <span>已用: {{ formatTokens(costStats.daily?.used) }} / {{ formatTokens(costStats.daily?.limit) }}</span>
              <span>请求: {{ costStats.daily?.requests ?? 0 }} 次</span>
            </div>
            <div class="cost-detail">
              <span>输入: {{ formatTokens(costStats.daily?.input_tokens) }}</span>
              <span>输出: {{ formatTokens(costStats.daily?.output_tokens) }}</span>
            </div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="cost-section">
            <div class="cost-title">本月消耗</div>
            <el-progress
              :percentage="monthlyPercent"
              :status="monthlyPercent >= 90 ? 'exception' : ''"
              :stroke-width="18"
              :show-text="true"
            />
            <div class="cost-detail">
              <span>已用: {{ formatTokens(costStats.monthly?.used) }} / {{ formatTokens(costStats.monthly?.limit) }}</span>
              <span>请求: {{ costStats.monthly?.requests ?? 0 }} 次</span>
            </div>
            <div class="cost-detail">
              <span>输入: {{ formatTokens(costStats.monthly?.input_tokens) }}</span>
              <span>输出: {{ formatTokens(costStats.monthly?.output_tokens) }}</span>
            </div>
          </div>
        </el-col>
      </el-row>
      <el-alert
        v-if="costStats.daily?.limit === 0 && costStats.monthly?.limit === 0"
        type="info"
        :closable="false"
        style="margin-top:12px"
        title="当前未设置每日/每月 token 限额，成本统计仅作参考。"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getAdminStatsApi, getLLMCostApi, type LLMCostStats, type AdminStats } from '@/api/admin'

const stats = ref<Partial<AdminStats>>({})
const costStats = ref<Partial<LLMCostStats>>({})

const dailyPercent = computed(() => {
  const used = costStats.value.daily?.used ?? 0
  const limit = costStats.value.daily?.limit ?? 0
  return limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
})

const monthlyPercent = computed(() => {
  const used = costStats.value.monthly?.used ?? 0
  const limit = costStats.value.monthly?.limit ?? 0
  return limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
})

function formatTokens(n: number | undefined) {
  if (n === undefined) return '-'
  if (n >= 1000000) return `${(n / 1000000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

onMounted(async () => {
  try { const resp = await getAdminStatsApi(); stats.value = resp.data }
  catch { /* ignore */ }
  try { const resp = await getLLMCostApi(); costStats.value = resp.data }
  catch { /* ignore */ }
})
</script>

<style scoped>
.admin-stats h3 { margin: 0 0 16px 0; }
.stat-value { font-size: 28px; font-weight: bold; color: #409eff; text-align: center; }
.cost-section { padding: 8px 0; }
.cost-title { font-size: 14px; color: #606266; margin-bottom: 12px; font-weight: 600; }
.cost-detail {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
}
</style>
