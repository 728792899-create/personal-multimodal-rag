import type { RequestOptions } from './types'


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
      throw new ApiError(
        typeof data === 'object' && data && 'detail' in data ? String(data.detail) : `请求失败（${response.status}）`,
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
