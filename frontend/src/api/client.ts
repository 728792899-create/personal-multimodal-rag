import type { RequestOptions } from './types'

let csrfToken = ''

export function setCsrfToken(value: string) {
  csrfToken = value
}

export function getCsrfToken() {
  return csrfToken
}

export class ApiError extends Error {
  status: number
  code: string
  requestId: string
  retryAfterSeconds: number | null

  constructor(message: string, options: { status?: number; code?: string; requestId?: string; retryAfterSeconds?: number | null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status ?? 0
    this.code = options.code ?? 'API_ERROR'
    this.requestId = options.requestId ?? ''
    this.retryAfterSeconds = options.retryAfterSeconds ?? null
  }
}

function validationIssueMessage(issue: unknown): string {
  if (!issue || typeof issue !== 'object') return ''
  const record = issue as Record<string, unknown>
  const message = typeof record.msg === 'string'
    ? record.msg.replace('Input should be a valid integer', '请输入有效整数')
    : ''
  const location = Array.isArray(record.loc)
    ? record.loc.filter((item) => !['body', 'query', 'path'].includes(String(item))).join('.')
    : ''
  return [location, message].filter(Boolean).join('：')
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail)) {
    const messages = detail.map(validationIssueMessage).filter(Boolean)
    return messages.length ? `参数校验失败：${messages.join('；')}` : fallback
  }
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    for (const key of ['message', 'msg', 'detail', 'error']) {
      if (key in record) return formatApiErrorDetail(record[key], fallback)
    }
  }
  return fallback
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timeoutMs = options.timeoutMs ?? 30_000
  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const handleCallerAbort = () => controller.abort()
  options.signal?.addEventListener('abort', handleCallerAbort, { once: true })

  try {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    const method = String(init.method || 'GET').toUpperCase()
    if (csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      headers.set('X-CSRF-Token', csrfToken)
    }
    const response = await fetch(path, {
      ...init,
      headers,
      credentials: 'same-origin',
      signal: controller.signal,
    })
    const contentType = response.headers.get('content-type') || ''
    const data = contentType.includes('application/json')
      ? await response.json()
      : await response.text()
    if (!response.ok) {
      const retryAfter = Number(response.headers.get('retry-after'))
      const fallback = `请求失败（${response.status}）`
      throw new ApiError(
        typeof data === 'object' && data && 'detail' in data
          ? formatApiErrorDetail(data.detail, fallback)
          : fallback,
        {
          status: response.status,
          code: response.status === 429 ? 'RATE_LIMITED' : 'HTTP_ERROR',
          requestId: response.headers.get('x-request-id') || '',
          retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : null,
        },
      )
    }
    return data as T
  } catch (error) {
    if (timedOut) {
      throw new ApiError('请求超时，请重试。', { status: 408, code: 'TIMEOUT' })
    }
    if (options.signal?.aborted) {
      throw new DOMException('Request cancelled', 'AbortError')
    }
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(error instanceof Error ? error.message : '网络请求失败', { code: 'NETWORK_ERROR' })
  } finally {
    window.clearTimeout(timeoutId)
    options.signal?.removeEventListener('abort', handleCallerAbort)
  }
}

export function jsonBody(payload: unknown): Pick<RequestInit, 'headers' | 'body'> {
  return {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}
