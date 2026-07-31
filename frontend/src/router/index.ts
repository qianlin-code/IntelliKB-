import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/store/user'
import { getUserInfoApi } from '@/api/auth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresAdmin?: boolean
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { requiresAuth: true, title: '工作台' },
      },
      {
        path: 'kbs',
        name: 'KBList',
        component: () => import('@/views/knowledge/KBList.vue'),
        meta: { requiresAuth: true, title: '知识库管理' },
      },
      {
        path: 'kbs/:kbId',
        name: 'KBDetail',
        component: () => import('@/views/knowledge/KBDetail.vue'),
        meta: { requiresAuth: true, title: '知识库详情' },
      },
      {
        path: 'qa/:kbId',
        name: 'QAPage',
        component: () => import('@/views/qa/QAPage.vue'),
        meta: { requiresAuth: true, title: '智能问答' },
      },
      {
        path: 'eval/:kbId',
        name: 'EvalDashboard',
        component: () => import('@/views/eval/EvalDashboard.vue'),
        meta: { requiresAuth: true, title: 'RAG 评测' },
      },
    ],
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false, title: '登录' },
  },
  {
    path: '/admin',
    component: () => import('@/views/admin/AdminLayout.vue'),
    redirect: '/admin/stats',
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: 'stats',
        name: 'AdminStats',
        component: () => import('@/views/admin/AdminStats.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '系统统计' },
      },
      {
        path: 'users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/AdminUsers.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '用户管理' },
      },
      {
        path: 'audit-logs',
        name: 'AdminAuditLogs',
        component: () => import('@/views/admin/AdminAuditLogs.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '审计日志' },
      },
      {
        path: 'system-config',
        name: 'AdminSystemConfig',
        component: () => import('@/views/admin/AdminSystemConfig.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '系统配置' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/404.vue'),
    meta: { title: '404' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()

  if (to.meta.requiresAuth === false) {
    next()
    return
  }

  if (!userStore.token) {
    next('/login')
    return
  }

  if (!userStore.userInfo) {
    try {
      const resp = await getUserInfoApi()
      userStore.userInfo = resp.data
    } catch {
      userStore.clearState()
      next('/login')
      return
    }
  }

  // Phase 10: 管理后台权限校验
  if (to.meta.requiresAdmin && userStore.userInfo) {
    const role = (userStore.userInfo as any).system_role || 'user'
    if (role !== 'admin' && role !== 'superadmin') {
      next('/dashboard')
      return
    }
  }

  next()
})

export default router
