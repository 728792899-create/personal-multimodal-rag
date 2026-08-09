import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LoginPage from './LoginPage.vue'


describe('LoginPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('submits the password without persisting it in browser storage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = mount(LoginPage, {
      props: { submitting: false, error: '' },
    })

    await wrapper.get('input[type="password"]').setValue('correct horse battery staple')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('submit')?.[0]).toEqual(['correct horse battery staple'])
    expect(setItem).not.toHaveBeenCalled()
  })

  it('announces authentication failures', () => {
    const wrapper = mount(LoginPage, {
      props: { submitting: false, error: 'Invalid administrator credentials' },
    })
    expect(wrapper.get('[role="alert"]').text()).toContain('管理员密码不正确')
  })

  it('uses Chinese semantics for visible product and session copy', () => {
    const wrapper = mount(LoginPage, {
      props: { submitting: false, error: '' },
    })

    expect(wrapper.get('#login-title').text()).toBe('个人多模态 RAG')
    expect(wrapper.text()).toContain('证据账本 · 本地')
    expect(wrapper.text()).toContain('有据智能')
    expect(wrapper.text()).toContain('混合检索')
    expect(wrapper.text()).toContain('证据溯源')
    expect(wrapper.text()).toContain('本地控制')
    expect(wrapper.text()).toContain('已启用 CSRF 防护')
    expect(wrapper.text()).toContain('仅 HTTP 可访问的会话令牌')
  })
})
