import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiRequest } from './client'


describe('apiRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('maps backend detail to Chinese while preserving status, request id, and retry-after', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Rate limit exceeded' }),
      {
        status: 429,
        headers: {
          'content-type': 'application/json',
          'retry-after': '17',
          'x-request-id': 'req-123',
        },
      },
    )))

    const error = await apiRequest('/api/ask').catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      message: '请求过于频繁，请稍后重试。',
      status: 429,
      requestId: 'req-123',
      retryAfterSeconds: 17,
    })
  })

  it('formats FastAPI validation arrays without leaking object coercion text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: [{ type: 'int_type', loc: ['body', 'candidate_k'], msg: 'Input should be a valid integer', input: null }] }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    )))

    await expect(apiRequest('/api/ask')).rejects.toMatchObject({
      message: '参数校验失败：候选池：请输入有效整数',
      status: 422,
    })
  })

  it('aborts and reports a bounded timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_path, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))

    const request = apiRequest('/api/slow', {}, { timeoutMs: 20 })
    const assertion = expect(request).rejects.toMatchObject({ code: 'TIMEOUT', status: 408 })
    await vi.advanceTimersByTimeAsync(21)

    await assertion
  })

  it('preserves caller cancellation instead of labeling it a timeout', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_path, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))

    const request = apiRequest('/api/ask', {}, { signal: controller.signal, timeoutMs: 5_000 })
    controller.abort()

    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
  })
})
