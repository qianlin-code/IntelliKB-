<template>
  <div class="member-manager">
    <div class="member-header">
      <span>成员列表 ({{ members.length }})</span>
      <el-button type="primary" size="small" @click="showAddDialog = true">
        <el-icon><Plus /></el-icon> 添加成员
      </el-button>
    </div>

    <el-table :data="members" stripe style="width: 100%">
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column label="角色" width="150">
        <template #default="{ row }">
          <el-tag
            :type="row.role === 'owner' ? 'danger' : row.role === 'editor' ? 'warning' : 'info'"
            size="small"
          >
            {{ roleLabel(row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="加入时间" width="120">
        <template #default="{ row }">{{ row.created_at?.slice(0, 10) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" v-if="isOwner">
        <template #default="{ row }">
          <template v-if="row.role !== 'owner'">
            <el-select
              :model-value="row.role"
              size="small"
              style="width: 90px"
              @change="(val: string) => onChangeRole(row.user_id, val)"
            >
              <el-option label="编辑者" value="editor" />
              <el-option label="访客" value="viewer" />
            </el-select>
            <el-popconfirm title="确认移除？" @confirm="onRemove(row.user_id)">
              <template #reference>
                <el-button size="small" type="danger" text>移除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加成员对话框 -->
    <el-dialog v-model="showAddDialog" title="添加成员" width="400px">
      <el-form :model="addForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="addForm.username" placeholder="输入用户名" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="addForm.role" style="width: 100%">
            <el-option label="编辑者" value="editor" />
            <el-option label="访客" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="onAdd">确认添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { listMembersApi, addMemberApi, updateMemberApi, removeMemberApi } from '@/api/member'
import type { MemberInfo } from '@/types'

const props = defineProps<{ kbId: number; isOwner: boolean }>()

const members = ref<MemberInfo[]>([])
const showAddDialog = ref(false)
const adding = ref(false)
const addForm = reactive({ username: '', role: 'viewer' })

function roleLabel(role: string) {
  return { owner: '所有者', editor: '编辑者', viewer: '访客' }[role] || role
}

async function loadMembers() {
  try {
    const resp = await listMembersApi(props.kbId)
    members.value = resp.data.members
  } catch { /* handled by interceptor */ }
}

async function onAdd() {
  if (!addForm.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  adding.value = true
  try {
    // 需要通过 username 查找 user_id。简化方案：用户名即 user_id
    // 实际项目应接入用户搜索 API
    const userId = parseInt(addForm.username)
    if (isNaN(userId)) {
      ElMessage.warning('请输入有效的用户 ID')
      return
    }
    await addMemberApi(props.kbId, { user_id: userId, role: addForm.role })
    ElMessage.success('成员已添加')
    showAddDialog.value = false
    addForm.username = ''
    await loadMembers()
  } finally {
    adding.value = false
  }
}

async function onChangeRole(userId: number, role: string) {
  await updateMemberApi(props.kbId, userId, { role })
  ElMessage.success('角色已更新')
  await loadMembers()
}

async function onRemove(userId: number) {
  await removeMemberApi(props.kbId, userId)
  ElMessage.success('成员已移除')
  await loadMembers()
}

onMounted(loadMembers)
</script>

<style scoped>
.member-manager { }
.member-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
</style>
