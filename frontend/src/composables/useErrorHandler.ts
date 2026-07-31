/**
 * Phase P0: 统一错误处理 composable
 *
 * 集中处理 axios / fetch / SSE 三类异常，提供：
 * - 用户友好的中文提示
 * - 401 统一跳转登录
 * - 429 成本限额提示
 * - 可选的静默模式（不弹 ElMessage）
 */
import { ElMessage } from 'element-plus'
import router from '@/router'
import { SSEError } from './useSSE'

export interface ErrorHandlerOptions {
  silent?: boolean
  defaultMessage?: string
}

export function useErrorHandler(options: ErrorHandlerOptions = {}) {
  function handle(error: unknown, context?: string) {
    let message = options.defaultMessage || '服务暂时不可用，请稍后重试。'
    let status = 0

    if (error instanceof SSEError) {
      status = error.status
      message = error.message
    } else if (error && typeof error === 'object' && 'response' in error) {
      const axiosError = error as { response?: { status?: number; data?: { message?: string; detail?: string } } }
      status = axiosError.response?.status || 0
      message =
        axiosError.response?.data?.message ||
        axiosError.response?.data?.detail ||
        (error as unknown as Error).message ||
        message
    } else if (error instanceof Error) {
      message = error.message || message
      if (error.name === 'AbortError') {
        // 用户主动取消，通常不需要提示
        return { status: -1, message: '已取消' }
      }
    }

    // 401 统一跳转登录
    if (status === 401) {
      message = '登录已过期，请重新登录'
      if (!options.silent) {
        ElMessage.error(message)
      }
      sessionStorage.removeItem('access_token')
      sessionStorage.removeItem('refresh_token')
      router.push('/login')
      return { status, message }
    }

    // 429 成本限额
    if (status === 429) {
      message = message.includes('限额') ? message : '请求过于频繁或已超出限额，请稍后再试。'
    }

    // 网络超时
    if (
      message.includes('timeout') ||
      message.includes('ECONNABORTED') ||
      message.includes('NetworkError')
    ) {
      message = '模型加载较慢或网络异常，请稍后重试。'
    }

    if (!options.silent) {
      const prefix = context ? `[${context}] ` : ''
      ElMessage.error(`${prefix}${message}`)
    }

    return { status, message }
  }

  return { handle }
}
