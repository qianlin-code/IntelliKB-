<template>
  <el-container class="app-layout">
    <!-- 顶栏 -->
    <el-header class="app-header">
      <div class="header-left">
        <span class="logo" @click="$router.push('/dashboard')">🧠 IntelliKB</span>
        <el-menu
          mode="horizontal"
          :default-active="activeNav"
          class="header-nav"
          @select="onNavSelect"
        >
          <el-menu-item index="/dashboard">工作台</el-menu-item>
          <el-menu-item index="/kbs">知识库管理</el-menu-item>
        </el-menu>
      </div>
      <div class="header-right">
        <OnboardingHelpButton class="header-help" />
        <el-dropdown trigger="click">
          <span class="user-info">
            👤 {{ userStore.username }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="isAdmin" @click="$router.push('/admin')">
                <el-icon><Setting /></el-icon> 系统管理
              </el-dropdown-item>
              <el-dropdown-item @click="onLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container class="app-main">
      <!-- 侧边栏 -->
      <el-aside width="240px" class="app-sidebar">
        <el-menu
          :default-active="activeMenu"
          class="sidebar-menu"
          @select="onSidebarSelect"
        >
          <el-menu-item index="/kbs">
            <el-icon><Folder /></el-icon>
            <span>我的知识库</span>
          </el-menu-item>
          <el-menu-item
            v-for="kb in kbStore.kbList"
            :key="kb.id"
            :index="`/kbs/${kb.id}`"
          >
            <el-icon><Document /></el-icon>
            <span>{{ kb.name }}</span>
          </el-menu-item>
          <el-menu-item index="__create__" class="create-kb-item">
            <el-icon><Plus /></el-icon>
            <span>创建知识库</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <!-- 内容区 -->
      <el-main class="app-content">
        <router-view />
      </el-main>
    </el-container>

    <!-- 底栏 -->
    <el-footer class="app-footer">
      v1.0.0 · IntelliKB 智能知识库平台
    </el-footer>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/store/user'
import { useKBStore } from '@/store/knowledgeBase'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import OnboardingHelpButton from '@/components/OnboardingHelpButton.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const kbStore = useKBStore()

const isAdmin = computed(() => {
  const role = (userStore.userInfo as any)?.system_role || 'user'
  return role === 'admin' || role === 'superadmin'
})

const activeNav = computed(() => {
  if (route.path.startsWith('/kbs')) return '/kbs'
  return '/dashboard'
})

const activeMenu = computed(() => {
  if (route.path === '/kbs') return '/kbs'
  if (route.path.startsWith('/kbs/')) return `/kbs/${route.params.kbId}`
  return ''
})

function onNavSelect(index: string) {
  router.push(index)
}

function onSidebarSelect(index: string) {
  if (index === '__create__') {
    router.push('/kbs')
  } else {
    router.push(index)
  }
}

function onLogout() {
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

onMounted(() => {
  kbStore.fetchKBList()
})
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  font-size: 18px;
  font-weight: 700;
  color: #409eff;
  cursor: pointer;
  white-space: nowrap;
}

.header-nav {
  border-bottom: none !important;
}

.header-nav .el-menu-item {
  height: 60px;
  line-height: 60px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-help {
  color: #606266;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #606266;
}

.app-main {
  min-height: calc(100vh - 90px);
}

.app-sidebar {
  background: #fafafa;
  border-right: 1px solid #e4e7ed;
  padding-top: 8px;
}

.sidebar-menu {
  border-right: none !important;
  background: transparent;
}

.create-kb-item {
  border-top: 1px solid #e4e7ed;
  margin-top: 8px;
  padding-top: 8px;
  color: #409eff !important;
}

.app-content {
  background: #f5f7fa;
  padding: 20px;
}

.app-footer {
  text-align: center;
  color: #909399;
  font-size: 12px;
  height: 30px;
  line-height: 30px;
  border-top: 1px solid #e4e7ed;
}
</style>
