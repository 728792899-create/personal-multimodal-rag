import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  clearDeepSeekRuntime,
  connectDeepSeekRuntime,
} from './providers'


describe('DeepSeek 临时连接接口', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('只在请求正文中发送密钥，并使用固定运行时端点', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ready' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await connectDeepSeekRuntime('sk-test-secret')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/providers/deepseek/runtime')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ api_key: 'sk-test-secret' })
    expect(path).not.toContain('sk-test-secret')
  })

  it('清除临时连接时不发送密钥正文', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'cleared' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await clearDeepSeekRuntime()

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/providers/deepseek/runtime')
    expect(init.method).toBe('DELETE')
    expect(init.body).toBeUndefined()
  })
})
