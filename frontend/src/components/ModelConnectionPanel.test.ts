import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ModelConnectionPanel from './ModelConnectionPanel.vue'
import type { ProviderStatus } from '../api'


function providerStatus(options: {
  runtimeActive?: boolean
  serverDeepSeekReady?: boolean
} = {}): ProviderStatus {
  const runtimeActive = options.runtimeActive ?? false
  const serverDeepSeekReady = options.serverDeepSeekReady ?? false
  return {
    status: 'ready',
    environment: 'test',
    fallback_allowed: true,
    runtime: {
      deepseek: {
        connected: runtimeActive,
        configured: runtimeActive,
        active: runtimeActive,
        status: runtimeActive ? 'ready' : 'not_configured',
        health: runtimeActive ? 'ready' : 'not_configured',
        runtime_override: runtimeActive,
        temporary: true,
        base_url: 'https://api.deepseek.com',
        model: 'deepseek-v4-flash',
      },
    },
    providers: {
      answer: {
        provider: runtimeActive
          ? 'deepseek_official'
          : serverDeepSeekReady
            ? 'openai_compatible_chat'
            : 'template',
        configured: true,
        health: serverDeepSeekReady ? 'not_checked' : 'ready',
        mode: runtimeActive || serverDeepSeekReady ? 'external' : 'offline',
        capabilities: ['answer'],
        ...(runtimeActive
          ? {
              model: 'deepseek-v4-flash',
              base_url: 'https://api.deepseek.com',
            }
          : serverDeepSeekReady
            ? {
                model: 'deepseek-v4-flash',
                base_url: 'https://api.deepseek.com',
              }
            : { model: '-', base_url: '' }),
      },
      embedding: {
        provider: 'mock',
        configured: true,
        mode: 'offline',
        capabilities: ['embeddings'],
      },
      vector_store: { provider: 'memory', configured: true },
    },
  }
}

describe('模型连接面板', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('连接并验证 DeepSeek，清空输入且不写入浏览器存储', async () => {
    const localStorageWrite = vi.spyOn(Storage.prototype, 'setItem')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ready' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(providerStatus({ runtimeActive: true })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
      attachTo: document.body,
    })

    const secretInput = wrapper.get<HTMLInputElement>('[data-testid="deepseek-api-key"]')
    expect(secretInput.attributes('type')).toBe('password')
    expect(secretInput.attributes('autocomplete')).toBe('off')
    expect(wrapper.get('[data-testid="connect-deepseek"]').attributes('disabled')).toBeDefined()

    await secretInput.setValue('sk-test-secret')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    expect(secretInput.element.value).toBe('')
    await flushPromises()

    expect(wrapper.get('[role="status"]').text()).toContain('连接验证通过')
    expect(wrapper.text()).toContain('临时连接已启用')
    expect(wrapper.find('[data-testid="deepseek-api-key"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="clear-deepseek"]').exists()).toBe(true)
    expect(wrapper.emitted('statusChange')).toHaveLength(1)
    expect(localStorageWrite).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
    expect(wrapper.html()).not.toContain('sk-test-secret')

    wrapper.unmount()
    localStorageWrite.mockRestore()
  })

  it('忽略服务端错误详情中的敏感内容，并允许重新输入后重试', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'sk-invalid-key 不能使用' }), {
        status: 502,
        headers: { 'content-type': 'application/json' },
      }),
    ))
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
      attachTo: document.body,
    })

    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-invalid-key')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('连接验证失败')
    expect(wrapper.get('[role="alert"]').text()).not.toContain('sk-invalid-key')
    expect(wrapper.get('[data-testid="retry-deepseek"]').text()).toBe('重试')
    await wrapper.get('[data-testid="retry-deepseek"]').trigger('click')
    expect(document.activeElement).toBe(wrapper.get('[data-testid="deepseek-api-key"]').element)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('服务端已连接时仍允许用临时密钥替换，但不显示清除按钮', () => {
    const wrapper = mount(ModelConnectionPanel, {
      props: {
        canManageProviders: true,
        providerStatus: providerStatus({ serverDeepSeekReady: true }),
        open: true,
      },
    })

    expect(wrapper.text()).toContain('服务端已连接')
    expect(wrapper.text()).toContain('输入新密钥将仅在当前服务进程中临时替换')
    expect(wrapper.find('[data-testid="deepseek-api-key"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="connect-deepseek"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="clear-deepseek"]').exists()).toBe(false)
  })

  it('运行时连接启用时仍显示输入框，并且只在此时显示清除按钮', () => {
    const wrapper = mount(ModelConnectionPanel, {
      props: {
        canManageProviders: true,
        providerStatus: providerStatus({ runtimeActive: true }),
        open: true,
      },
    })

    expect(wrapper.text()).toContain('临时连接已启用')
    expect(wrapper.find('[data-testid="deepseek-api-key"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="clear-deepseek"]').exists()).toBe(true)
  })

  it('清除临时连接后恢复并保留服务端连接状态', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'cleared' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(providerStatus({ serverDeepSeekReady: true })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: {
        canManageProviders: true,
        providerStatus: providerStatus({ runtimeActive: true }),
        open: true,
      },
    })

    await wrapper.get('[data-testid="clear-deepseek"]').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE')
    expect(wrapper.get('[role="status"]').text()).toContain('已恢复服务端连接')
    expect(wrapper.text()).toContain('服务端已连接')
    expect(wrapper.find('[data-testid="clear-deepseek"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="deepseek-api-key"]').exists()).toBe(true)
  })

  it.each([
    [401, '登录已失效'],
    [403, '会话校验失败'],
  ])('把 %s 鉴权错误与密钥错误区分开', async (status, expected) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: '鉴权失败' }), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    ))
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
    })

    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-invalid-key')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain(expected)
    expect(wrapper.get('[role="alert"]').text()).not.toContain('密钥验证失败')
  })

  it('明确说明数据发送范围，并要求显式确认后才能连接', async () => {
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
    })

    expect(wrapper.text()).toContain('服务端转发到 DeepSeek 官方接口')
    expect(wrapper.text()).toContain('问题和检索命中的证据片段发送给 DeepSeek')
    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-test-secret')
    expect(wrapper.get('[data-testid="connect-deepseek"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    expect(wrapper.get('[data-testid="connect-deepseek"]').attributes('disabled')).toBeUndefined()
  })

  it('没有受保护管理员会话时禁用连接和清除操作', () => {
    const wrapper = mount(ModelConnectionPanel, {
      props: {
        canManageProviders: false,
        providerStatus: providerStatus({ runtimeActive: true }),
        open: true,
      },
    })

    expect(wrapper.text()).toContain('当前会话没有模型连接管理权限')
    expect(wrapper.get('[data-testid="deepseek-api-key"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="deepseek-data-consent"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="connect-deepseek"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="clear-deepseek"]').attributes('disabled')).toBeDefined()
  })

  it('关闭抽屉不会中止已经提交的连接请求', async () => {
    let finishPost!: (response: Response) => void
    const delayedPost = new Promise<Response>((resolve) => {
      finishPost = resolve
    })
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => delayedPost)
      .mockResolvedValueOnce(new Response(JSON.stringify(providerStatus({ runtimeActive: true })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
    })

    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-test-secret')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    const submittedSignal = fetchMock.mock.calls[0][1]?.signal as AbortSignal

    await wrapper.setProps({ open: false })
    expect(submittedSignal.aborted).toBe(false)

    finishPost(new Response(JSON.stringify({
      status: 'ready',
      connection: providerStatus({ runtimeActive: true }).runtime?.deepseek,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    await flushPromises()

    expect(submittedSignal.aborted).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('连接验证通过')
  })

  it('连接已生效但后续状态刷新失败时不误报连接失败', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'ready',
        connection: providerStatus({ runtimeActive: true }).runtime?.deepseek,
      }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '暂时不可用' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: true },
    })

    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-test-secret')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('连接已生效但状态刷新失败')
    expect(wrapper.text()).toContain('临时连接已启用')
  })

  it('初始状态未知时仍以成功响应显示已连接，不依赖后续状态刷新', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'ready',
        connection: providerStatus({ runtimeActive: true }).runtime?.deepseek,
      }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '暂时不可用' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: null, open: true },
    })

    await wrapper.get('[data-testid="deepseek-api-key"]').setValue('sk-test-secret')
    await wrapper.get('[data-testid="deepseek-data-consent"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="status"]').text()).toContain('连接已生效但状态刷新失败')
    expect(wrapper.text()).toContain('临时连接已启用')
    expect(wrapper.emitted('statusChange')).toHaveLength(1)
  })

  it('每次从关闭状态打开面板都会主动刷新连接状态', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(providerStatus({ serverDeepSeekReady: true })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ModelConnectionPanel, {
      props: { canManageProviders: true, providerStatus: providerStatus(), open: false },
    })

    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/providers/status')
    expect(wrapper.text()).toContain('服务端已连接')

    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
