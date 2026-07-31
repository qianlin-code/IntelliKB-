<template>
  <div class="eval-dashboard">
    <div class="eval-header">
      <el-button text @click="$router.back()"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
      <h3>RAG 评测仪表盘</h3>
    </div>

    <!-- 操作区 -->
    <el-card class="eval-actions" shadow="hover">
      <template #header>评测操作</template>
      <el-row :gutter="16" align="middle">
        <el-col :span="4">
          <el-input-number v-model="topK" :min="1" :max="20" placeholder="Top-K" />
        </el-col>
        <el-col :span="4">
          <el-select v-model="provider" placeholder="Provider" clearable>
            <el-option label="ollama (本地)" value="ollama" />
            <el-option label="deepseek (云端)" value="deepseek" />
          </el-select>
        </el-col>
        <!-- Phase 8: 重写策略选择 -->
        <el-col :span="4">
          <el-select v-model="rewriteStrategy" placeholder="重写策略" clearable>
            <el-option label="A: 指代消解 (默认)" value="A" />
            <el-option label="B: 问题拆解" value="B" />
            <el-option label="C: 关键词提取" value="C" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-button type="primary" :loading="running" @click="runEval" :disabled="!kbId">
            执行评测
          </el-button>
        </el-col>
        <el-col :span="6">
          <el-button :loading="synthing" @click="synthesizeQueries">
            生成评测查询 ({{ synthCount }})
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 指标卡片 -->
    <el-row :gutter="16" class="metrics-row" v-if="latestRun">
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>Hit Rate@3</template>
          <div class="metric-value">{{ (latestRun.hit_rate_at_3 * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>Hit Rate@5</template>
          <div class="metric-value">{{ (latestRun.hit_rate_at_5 * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>MRR</template>
          <div class="metric-value">{{ (latestRun.mrr * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>Recall@5</template>
          <div class="metric-value">{{ (latestRun.recall_at_5 * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Phase 8: 模型 × 重写策略对比矩阵 -->
    <el-card class="compare-card" shadow="hover" v-if="compareMatrix.length >= 2">
      <template #header>模型 × 重写策略对比矩阵</template>
      <el-table :data="compareMatrix" stripe size="small">
        <el-table-column prop="label" label="配置" width="180" />
        <el-table-column label="Hit@5" width="100">
          <template #default="{ row }">{{ (row.hit_rate_at_5 * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="MRR" width="100">
          <template #default="{ row }">{{ (row.mrr * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="Recall@5" width="100">
          <template #default="{ row }">{{ (row.recall_at_5 * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="查询数" width="80">
          <template #default="{ row }">{{ row.query_count }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="160" />
      </el-table>
    </el-card>

    <!-- Phase 8: Tabs — 历史 + Badcase -->
    <el-card class="history-card" shadow="hover">
      <template #header>
        <el-tabs v-model="activeTab" @tab-change="onTabChange">
          <el-tab-pane label="评测历史" name="history" />
          <el-tab-pane label="Badcase 分析" name="badcase" />
        </el-tabs>
      </template>

      <!-- 历史记录 -->
      <el-table v-if="activeTab === 'history'" :data="runs" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="provider" label="Provider" width="100" />
        <!-- Phase 8: 重写策略列 -->
        <el-table-column prop="rewrite_strategy" label="策略" width="70">
          <template #default="{ row }">
            <el-tag v-if="row.rewrite_strategy" size="small" type="warning">{{ row.rewrite_strategy }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="query_count" label="查询数" width="80" />
        <el-table-column label="Hit@3" width="80">
          <template #default="{ row }">{{ (row.hit_rate_at_3 * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="Hit@5" width="80">
          <template #default="{ row }">{{ (row.hit_rate_at_5 * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="MRR" width="80">
          <template #default="{ row }">{{ (row.mrr * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="Recall@5" width="90">
          <template #default="{ row }">{{ (row.recall_at_5 * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="160" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="danger" link @click="viewBadcases(row.id)">Badcase</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Phase 8: Badcase 面板 -->
      <div v-if="activeTab === 'badcase'">
        <div class="badcase-toolbar">
          <el-select v-model="badcaseRunId" placeholder="选择评测记录" @change="loadBadcases" style="width: 240px">
            <el-option v-for="r in runs" :key="r.id" :label="`#${r.id} ${r.provider} ${r.rewrite_strategy || ''} (${r.created_at?.slice(0,10)})`" :value="r.id" />
          </el-select>
          <span v-if="badcases.length" class="badcase-count">共 {{ badcases.length }} 条未命中</span>
        </div>
        <el-table v-if="badcases.length" :data="badcases" stripe size="small" max-height="500">
          <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
          <el-table-column label="期望文档" width="120">
            <template #default="{ row }">
              <el-tag v-for="did in parseJsonArr(row.expected_doc_ids)" :key="did" size="small" type="success" style="margin:1px">{{ did }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="实际Top-5" width="160">
            <template #default="{ row }">
              <el-tag v-for="cid in parseJsonArr(row.retrieved_chunk_ids).slice(0,5)" :key="cid" size="small" type="danger" style="margin:1px">{{ cid }}</el-tag>
              <span v-if="parseJsonArr(row.retrieved_chunk_ids).length === 0" style="color:#909399">空</span>
            </template>
          </el-table-column>
          <el-table-column label="延迟" width="80">
            <template #default="{ row }">{{ row.latency_ms }}ms</template>
          </el-table-column>
        </el-table>
        <el-empty v-else-if="badcaseRunId && !loadingBadcases" description="该次评测无 badcase（全部命中）" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { synthesizeQueries as synthApi, runEval as runEvalApi, listEvalRuns, listBadcases } from '@/api/eval'

const route = useRoute()
const kbId = computed(() => Number(route.params.kbId))

const topK = ref(5)
const provider = ref('')
const rewriteStrategy = ref('')  // Phase 8
const synthCount = ref(20)
const running = ref(false)
const synthing = ref(false)
const runs = ref<any[]>([])
const latestRun = computed(() => runs.value[0] || null)

// Phase 8: 模型 × 重写策略对比矩阵
const compareMatrix = computed(() => {
  // 取最近 6 条评测结果作为对比
  if (runs.value.length < 2) return []
  const recent = runs.value.slice(0, 6)
  return recent.map(r => ({
    ...r,
    label: `${r.provider === 'ollama' ? '本地' : '云端'} ${r.rewrite_strategy ? '策略' + r.rewrite_strategy : '(默认)'}`,
  }))
})

async function loadHistory() {
  try {
    const resp = await listEvalRuns(kbId.value)
    runs.value = resp.data?.items || []
  } catch { /* ignore */ }
}

async function synthesizeQueries() {
  synthing.value = true
  try {
    const resp = await synthApi(kbId.value, synthCount.value)
    ElMessage.success(`已生成 ${resp.data?.generated || 0} 条评测查询`)
    loadHistory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '生成失败')
  } finally {
    synthing.value = false
  }
}

async function runEval() {
  running.value = true
  try {
    const resp = await runEvalApi(kbId.value, topK.value, provider.value || undefined, rewriteStrategy.value || undefined)
    ElMessage.success(`评测完成: MRR=${(resp.data?.mrr * 100).toFixed(1)}%`)
    loadHistory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '评测失败')
  } finally {
    running.value = false
  }
}

// Phase 8: Badcase 分析
const activeTab = ref('history')
const badcaseRunId = ref<number | null>(null)
const badcases = ref<any[]>([])
const loadingBadcases = ref(false)

function parseJsonArr(s: string): number[] {
  try { return JSON.parse(s) } catch { return [] }
}

async function viewBadcases(runId: number) {
  activeTab.value = 'badcase'
  badcaseRunId.value = runId
  await loadBadcases()
}

async function loadBadcases() {
  if (!badcaseRunId.value) return
  loadingBadcases.value = true
  try {
    const resp = await listBadcases(badcaseRunId.value)
    badcases.value = resp.data?.items || []
  } catch { badcases.value = [] }
  finally { loadingBadcases.value = false }
}

function onTabChange(tabName: string) {
  if (tabName === 'badcase' && runs.value.length && !badcaseRunId.value) {
    badcaseRunId.value = runs.value[0]?.id || null
    loadBadcases()
  }
}

onMounted(() => { loadHistory() })
</script>

<style scoped>
.eval-dashboard { padding: 16px; max-width: 1000px; margin: 0 auto; }
.eval-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.eval-header h3 { margin: 0; }
.eval-actions { margin-bottom: 16px; }
.metrics-row { margin-bottom: 16px; }
.metric-value { font-size: 28px; font-weight: bold; color: #409eff; text-align: center; }
.compare-card { margin-bottom: 16px; }
.compare-item { margin-bottom: 12px; }
.compare-item span { display: block; margin-bottom: 4px; font-size: 13px; color: #606266; }
.history-card { margin-top: 16px; }
/* Phase 8: Badcase 面板 */
.badcase-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}
.badcase-count {
  font-size: 13px;
  color: #e6a23c;
  font-weight: 600;
}
</style>
