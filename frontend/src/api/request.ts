import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios'
import router from '@/router'
import type { ApiResponse } from '@/types'
import { useErrorHandler } from '@/composables/useErrorHandler'

// 扩展 axios 配置
declare module 'axios' {
  interface InternalAxiosRequestConfig {
    silent?: boolean
  }
}

const { handle: handleError } = useErrorHandler({ silent: true })

const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// 是否正在刷新 Token
let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

function resolvePendingRequests(token: string) {
  pendingRequests.forEach((cb) => cb(token))
  pendingRequests = []
}

// 请求拦截器
request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = sessionStorage.getItem('access_token')
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器
request.interceptors.response.use(
  (response: AxiosResponse) => {
    const res = response.data
    if (res.code && res.code >= 400) {
      if (!response.config.silent) {
        handleError(new Error(res.message || '请求失败'), '请求')
      }
      return Promise.reject(new Error(res.message))
    }
    return res
  },
  async (error) => {
    const originalRequest = error.config
    const isLoginRequest = originalRequest?.url?.includes('/auth/login')
    const status = error.response?.status

    // 401 登录接口直接透传
    if (status === 401 && isLoginRequest) {
      return Promise.reject(error)
    }

    // 401 尝试刷新 Token（refresh 逻辑保留在拦截器内，避免循环触发）
    if (status === 401 && !originalRequest._retry) {
      const refreshToken = sessionStorage.getItem('refresh_token')
      if (!refreshToken) {
        handleError(error, '认证')
        return Promise.reject(error)
      }

      if (!isRefreshing) {
        isRefreshing = true
        originalRequest._retry = true
        try {
          const resp = await axios.post('/api/v1/auth/refresh', {
            refresh_token: refreshToken,
          })
          const data = resp.data.data
          sessionStorage.setItem('access_token', data.access_token)
          sessionStorage.setItem('refresh_token', data.refresh_token)
          resolvePendingRequests(data.access_token)
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`
          return request(originalRequest)
        } catch {
          handleError(error, '认证')
          return Promise.reject(error)
        } finally {
          isRefreshing = false
        }
      } else {
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(request(originalRequest))
          })
        })
      }
    }

    // 业务错误统一处理（silent 模式由调用方控制）
    if (!originalRequest?.silent) {
      handleError(error, '请求')
    }
    return Promise.reject(error)
  },
)

export function get<T = unknown>(url: string, params?: Record<string, unknown>, config?: Record<string, unknown>) {
  return request.get<unknown, ApiResponse<T>>(url, { params, ...config })
}

export function post<T = unknown>(url: string, data?: Record<string, unknown>, config?: Record<string, unknown>) {
  return request.post<unknown, ApiResponse<T>>(url, data, config)
}

export function put<T = unknown>(url: string, data?: Record<string, unknown>, config?: Record<string, unknown>) {
  return request.put<unknown, ApiResponse<T>>(url, data, config)
}

export function patch<T = unknown>(url: string, data?: Record<string, unknown>, config?: Record<string, unknown>) {
  return request.patch<unknown, ApiResponse<T>>(url, data, config)
}

export function del<T = unknown>(url: string, config?: Record<string, unknown>) {
  return request.delete<unknown, ApiResponse<T>>(url, config)
}

export default request
