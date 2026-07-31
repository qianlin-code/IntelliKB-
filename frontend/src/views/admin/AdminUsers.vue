<template>
  <div class="admin-users">
    <div class="page-header">
      <h3>用户管理</h3>
      <el-input v-model="searchQuery" placeholder="搜索用户名或邮箱" style="width:240px" clearable @input="loadUsers" />
    </div>
    <el-table :data="users" stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="email" label="邮箱" />
      <el-table-column label="系统角色" width="140">
        <template #default="{ row }">
          <el-select v-model="row.system_role" size="small" @change="(v: string) => changeRole(row.id, v)">
            <el-option label="superadmin" value="superadmin" />
            <el-option label="admin" value="admin" />
            <el-option label="user" value="user" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{ row.is_active ? '正常' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="注册时间" width="180" />
    </el-table>
    <el-pagination v-if="total > pageSize" layout="prev,next" :total="total" :page-size="pageSize" @current-change="(p: number) => { page = p; loadUsers() }" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { listUsersApi, updateUserRoleApi } from '@/api/admin'

const users = ref<any[]>([])
const loading = ref(false)
const searchQuery = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

async function loadUsers() {
  loading.value = true
  try {
    const resp = await listUsersApi(page.value, pageSize.value, searchQuery.value || undefined)
    users.value = resp.data.items
    total.value = resp.data.total
  } catch { /* 403 handled by router guard */ }
  finally { loading.value = false }
}

async function changeRole(userId: number, role: string) {
  try {
    await updateUserRoleApi(userId, role)
    ElMessage.success('角色已更新')
  } catch { ElMessage.error('更新失败') }
}

onMounted(() => loadUsers())
</script>

<style scoped>
.admin-users h3 { margin: 0; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
</style>
