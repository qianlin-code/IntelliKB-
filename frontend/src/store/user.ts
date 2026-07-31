import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { loginApi, logoutApi, getUserInfoApi } from '@/api/auth'
import type { UserInfo } from '@/types'
import { ElMessage } from 'element-plus'

export const useUserStore = defineStore('user', () => {
  const token = ref<string | null>(sessionStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(sessionStorage.getItem('refresh_token'))
  const userInfo = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const username = computed(() => userInfo.value?.username || '')

  function saveTokens(access: string, refresh: string) {
    token.value = access
    refreshToken.value = refresh
    sessionStorage.setItem('access_token', access)
    sessionStorage.setItem('refresh_token', refresh)
  }

  function clearState() {
    token.value = null
    refreshToken.value = null
    userInfo.value = null
    sessionStorage.removeItem('access_token')
    sessionStorage.removeItem('refresh_token')
  }

  async function login(username: string, password: string) {
    const resp = await loginApi({ username, password })
    saveTokens(resp.data.access_token, resp.data.refresh_token)
    await fetchUserInfo()
  }

  async function logout() {
    try {
      await logoutApi()
    } catch {
      /* 忽略 */
    }
    clearState()
    ElMessage.success('已退出登录')
  }

  async function fetchUserInfo() {
    const resp = await getUserInfoApi()
    userInfo.value = resp.data
  }

  return {
    token, refreshToken, userInfo,
    isLoggedIn, username,
    login, logout, fetchUserInfo, clearState,
  }
})
