<template>
  <div class="admin-audit-logs">
    <h3>审计日志</h3>
    <div class="filters">
      <el-input v-model="filters.user_id" placeholder="用户 ID" style="width:120px" clearable />
      <el-select v-model="filters.action" placeholder="操作类型" clearable style="width:180px">
        <el-option v-for="a in actions" :key="a" :label="a" :value="a" />
      </el-select>
      <el-select v-model="filters.resource_type" placeholder="资源类型" clearable style="width:130px">
        <el-option label="kb" value="kb" />
        <el-option label="document" value="document" />
        <el-option label="user" value="user" />
        <el-option label="conversation" value="conversation" />
        <el-option label="system_config" value="system_config" />
      </el-select>
      <el-date-picker v-model="filters.start_date" type="date" placeholder="开始日期" style="width:160px" />
      <el-date-picker v-model="filters.end_date" type="date" placeholder="结束日期" style="width:160px" />
      <el-button type="primary" @click="loadLogs">查询</el-button>
    </div>
    <el-table :data="logs" stripe v-loading="loading" max-height="600" size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="user_id" label="用户" width="70" />
      <el-table-column prop="action" label="操作" width="160">
        <template #default="{ row }">
          <el-tag size="small" type="warning">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="资源" width="160">
        <template #default="{ row }">{{ row.resource_type }}#{{ row.resource_id }}</template>
      </el-table-column>
      <el-table-column prop="details" label="详情" min-width="160" show-overflow-tooltip />
      <el-table-column prop="ip_address" label="IP" width="140" />
      <el-table-column prop="created_at" label="时间" width="180" />
    </el-table>
    <el-pagination v-if="total > pageSize" layout="prev,next" :total="total" :page-size="pageSize" @current-change="(p: number) => { page = p; loadLogs() }" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { listAuditLogsApi } from '@/api/admin'

const actions = ['LOGIN','LOGOUT','API_KEY_CREATE','API_KEY_DELETE','KB_CREATE','KB_UPDATE','KB_DELETE','KB_MEMBER_ADD','KB_MEMBER_REMOVE','KB_TRANSFER','DOCUMENT_UPLOAD','DOCUMENT_DELETE','AGENT_CHAT','EVAL_RUN','USER_ROLE_CHANGE','SYSTEM_CONFIG_UPDATE']

const logs = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const filters = reactive<Record<string, any>>({ user_id: '', action: '', resource_type: '', start_date: '', end_date: '' })

async function loadLogs() {
  loading.value = true
  try {
    const p: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (filters.user_id) p.user_id = Number(filters.user_id)
    if (filters.action) p.action = filters.action
    if (filters.resource_type) p.resource_type = filters.resource_type
    if (filters.start_date) p.start_date = filters.start_date
    if (filters.end_date) p.end_date = filters.end_date
    const resp = await listAuditLogsApi(p)
    logs.value = resp.data.items
    total.value = resp.data.total
  } catch { /* ignore */ }
  finally { loading.value = false }
}

onMounted(() => loadLogs())
</script>

<style scoped>
.admin-audit-logs h3 { margin: 0 0 12px 0; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
</style>
