import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiRequest } from './client'


describe('apiRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('surfaces backend detail, status, request id, and retry-after', async () => {
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
      message: 'Rate limit exceeded',
      status: 429,
      requestId: 'req-123',
      retryAfterSeconds: 17,
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
