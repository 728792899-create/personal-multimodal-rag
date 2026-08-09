import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MemberManagementPanel from './MemberManagementPanel.vue'


function member(overrides: Record<string, unknown> = {}) {
  return {
    user_id: 'owner',
    username: 'admin',
    display_name: '管理员',
    workspace_id: 'default',
    role: 'admin',
    is_active: true,
    must_change_password: false,
    disabled_at: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
    ...overrides,
  }
}

describe('MemberManagementPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('加载成员并在创建后立即清空临时密码', async () => {
    const created = member({
      user_id: 'reader-1',
      username: 'reader',
      display_name: '阅读者',
      role: 'viewer',
      must_change_password: true,
    })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ members: [member()] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ member: created }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(MemberManagementPanel, {
      props: { open: true, currentUserId: 'owner' },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('@admin')

    await wrapper.get('input[name="new-member-username"]').setValue('reader')
    await wrapper.get('input[name="new-member-display-name"]').setValue('阅读者')
    const secretInput = wrapper.get<HTMLInputElement>('input[name="temporary-password"]')
    await secretInput.setValue('temporary reader password')
    await wrapper.get('.member-form').trigger('submit')
    expect(secretInput.element.value).toBe('')
    await flushPromises()

    expect(wrapper.text()).toContain('@reader')
    expect(wrapper.text()).toContain('必须修改临时密码')
    expect(wrapper.html()).not.toContain('temporary reader password')
    expect(fetchMock.mock.calls[1][1]?.method).toBe('POST')
  })

  it('当前管理员改角色或重置密码后通知顶层刷新会话', async () => {
    const demoted = member({ role: 'editor' })
    const reset = member({ role: 'admin', must_change_password: true })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ members: [member()] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ member: demoted }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ member: reset, sessions_revoked: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(MemberManagementPanel, {
      props: { open: true, currentUserId: 'owner' },
    })
    await flushPromises()

    await wrapper.get('.member-controls select').setValue('editor')
    await flushPromises()
    expect(wrapper.emitted('currentUserChanged')).toHaveLength(1)

    await wrapper.findAll('.member-actions button')[1].trigger('click')
    await wrapper.get('.member-reset input').setValue('replacement password')
    await wrapper.get('.member-reset').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('currentUserChanged')).toHaveLength(2)
    expect(fetchMock.mock.calls[1][1]?.method).toBe('PATCH')
    expect(fetchMock.mock.calls[2][1]?.method).toBe('POST')
  })
})
