/**
 * 统一 SSE 解析 composable
 *
 * Phase P0 增强：
 * - 支持 POST + JSON body（解决 GET URL 长度限制）
 * - 支持 query param 认证（access_token / Cookie）
 * - 按 \n\n 切分 frame 后，对 data: 行做拼接（允许多行 data），再 yield 事件。
 *
 * Phase 4 后端不实现事件回放，id: / Last-Event-ID 为预留字段。
 */
import { ref } from 'vue'

export class SSEError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'SSEError'
    this.status = status
  }
}

export interface SSEEvent {
  event: string
  data: string
}

export interface SSEOptions {
  signal?: AbortSignal
  method?: 'GET' | 'POST'
  body?: Record<string, unknown>
  headers?: Record<string, string>
  /** SSE 无法设置自定义 Header，可通过 access_token query param 传递 JWT */
  token?: string
}

/**
 * 使用 refresh_token 换取新的 access_token。
 * 成功后会更新 sessionStorage 中的双 token。
 */
async function refreshAccessToken(oldAccessToken?: string): Promise<string> {
  const refreshToken = sessionStorage.getItem('refresh_token')
  if (!refreshToken) {
    throw new Error('No refresh token')
  }

  const body: Record<string, string> = { refresh_token: refreshToken }
  if (oldAccessToken) {
    body.current_access_token = oldAccessToken
  }

  const resp = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`Refresh failed: ${resp.status} ${text}`)
  }

  const json = await resp.json()
  const data = json.data ?? json
  const newAccessToken = data.access_token
  const newRefreshToken = data.refresh_token

  if (!newAccessToken) {
    throw new Error('No access_token in refresh response')
  }

  sessionStorage.setItem('access_token', newAccessToken)
  if (newRefreshToken) {
    sessionStorage.setItem('refresh_token', newRefreshToken)
  }

  return newAccessToken
}

export function useSSE(url: string, options: SSEOptions = {}) {
  const lastEventId = ref<string | null>(null)

  async function* stream(): AsyncGenerator<SSEEvent> {
    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
      ...options.headers,
    }
    if (lastEventId.value) {
      headers['Last-Event-ID'] = lastEventId.value
    }

    const fetchOptions: RequestInit = {
      method: options.method || 'GET',
      signal: options.signal,
      headers,
    }
    if (fetchOptions.method === 'POST' && options.body) {
      headers['Content-Type'] = 'application/json'
      fetchOptions.body = JSON.stringify(options.body)
    }

    // SSE 无法设置 Authorization header，优先通过 query param 传递 token。
    // 若 token 过期导致 401，自动使用 refresh_token 刷新并重试一次。
    let currentToken = options.token
    let requestUrl = url
    let retried401 = false
    let response: Response

    while (true) {
      if (options.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }

      if (currentToken) {
        const separator = url.includes('?') ? '&' : '?'
        requestUrl = `${url}${separator}access_token=${encodeURIComponent(currentToken)}`
      }

      response = await fetch(requestUrl, fetchOptions)

      if (response.status === 401 && currentToken && !retried401) {
        try {
          currentToken = await refreshAccessToken(currentToken)
          retried401 = true
          continue
        } catch (refreshErr) {
          if (options.signal?.aborted) {
            throw new DOMException('Aborted', 'AbortError')
          }
          // 刷新失败：保留原 401 响应，下方统一抛错
        }
      }

      if (!response.ok) {
        throw new SSEError(
          `SSE connection failed: ${response.status} ${response.statusText}`,
          response.status,
        )
      }
      break
    }

    if (!response.body) {
      throw new Error('Response body is null — streaming not supported')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 按 \n\n 切分完整 frame
        const frames = buffer.split('\n\n')
        buffer = frames.pop()!  // 最后一个可能不完整，保留在 buffer

        for (const frame of frames) {
          if (!frame.trim()) continue

          let eventType = ''
          const dataLines: string[] = []

          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              // 多行 data 拼接（用 \n 连接）
              dataLines.push(line.slice(5).trim())
            } else if (line.startsWith('id:')) {
              // 记录 Last-Event-ID（预留，Phase 4 后端不发送 id: 行）
              lastEventId.value = line.slice(3).trim()
            }
          }

          // 即使没有 event: 行，只要有 data: 行就 yield
          if (dataLines.length > 0) {
            yield { event: eventType, data: dataLines.join('\n') }
          }
        }
      }
    } finally {
      // 确保 reader 释放（即使循环因 AbortSignal 中断）
      reader.releaseLock()
    }
  }

  return { stream, lastEventId }
}
