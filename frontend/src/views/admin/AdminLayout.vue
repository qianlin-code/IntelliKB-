<template>
  <div class="admin-layout">
    <div class="admin-sidebar">
      <div class="admin-sidebar-title">系统管理</div>
      <el-menu :default-active="activeMenu" router @select="onMenuSelect">
        <el-menu-item index="/admin/stats">
          <el-icon><DataAnalysis /></el-icon> 系统统计
        </el-menu-item>
        <el-menu-item index="/admin/users">
          <el-icon><User /></el-icon> 用户管理
        </el-menu-item>
        <el-menu-item index="/admin/audit-logs">
          <el-icon><Document /></el-icon> 审计日志
        </el-menu-item>
        <el-menu-item index="/admin/system-config">
          <el-icon><Setting /></el-icon> 系统配置
        </el-menu-item>
      </el-menu>
      <div class="admin-sidebar-footer">
        <el-button text @click="$router.push('/dashboard')">
          <el-icon><ArrowLeft /></el-icon> 返回前台
        </el-button>
      </div>
    </div>
    <div class="admin-content">
      <router-view />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { DataAnalysis, User, Document, Setting, ArrowLeft } from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)

function onMenuSelect() {}
</script>

<style scoped>
.admin-layout {
  display: flex;
  height: calc(100vh - 60px);
}
.admin-sidebar {
  width: 200px;
  flex-shrink: 0;
  border-right: 1px solid #e4e7ed;
  background: #fafafa;
  display: flex;
  flex-direction: column;
}
.admin-sidebar-title {
  padding: 16px;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px solid #e4e7ed;
}
.admin-sidebar :deep(.el-menu) {
  border-right: none;
  background: transparent;
}
.admin-sidebar-footer {
  margin-top: auto;
  padding: 12px;
  border-top: 1px solid #e4e7ed;
}
.admin-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}
</style>
