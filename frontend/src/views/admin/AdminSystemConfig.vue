<template>
  <div class="admin-system-config">
    <h3>系统配置</h3>
    <div class="section">
      <h4>静态配置 (来自 .env)</h4>
      <el-descriptions v-if="staticConfig" :column="1" border size="small">
        <el-descriptions-item v-for="(v, k) in staticConfig" :key="k" :label="String(k)">{{ v }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div class="section" style="margin-top:20px">
      <h4>动态配置（可热更新）</h4>
      <el-table :data="configItems" stripe size="small" v-loading="loading">
        <el-table-column prop="key" label="键" width="200" />
        <el-table-column prop="value" label="值">
          <template #default="{ row }">
            <template v-if="editKey === row.key">
              <el-input v-model="editValue" size="small" style="width:200px" />
              <el-button size="small" type="primary" @click="saveConfig(row.key)">保存</el-button>
              <el-button size="small" @click="editKey = ''">取消</el-button>
            </template>
            <template v-else>
              <el-tag size="small">{{ row.value }}</el-tag>
              <el-button size="small" link type="primary" @click="startEdit(row)">编辑</el-button>
            </template>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" />
        <el-table-column prop="updated_at" label="更新时间" width="180" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemConfigApi, updateSystemConfigApi } from '@/api/admin'

const configItems = ref<any[]>([])
const staticConfig = ref<Record<string, unknown> | null>(null)
const loading = ref(false)
const editKey = ref('')
const editValue = ref('')

async function loadConfig() {
  loading.value = true
  try {
    const resp = await getSystemConfigApi()
    configItems.value = resp.data.items || []
    staticConfig.value = resp.data.static_config || {}
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function startEdit(row: any) {
  editKey.value = row.key
  editValue.value = row.value
}

async function saveConfig(key: string) {
  try {
    await updateSystemConfigApi(key, editValue.value)
    ElMessage.success('配置已更新')
    editKey.value = ''
    loadConfig()
  } catch { ElMessage.error('更新失败') }
}

onMounted(() => loadConfig())
</script>

<style scoped>
.admin-system-config h3 { margin: 0 0 16px 0; }
.section h4 { margin: 0 0 8px 0; font-size: 14px; color: #606266; }
</style>
