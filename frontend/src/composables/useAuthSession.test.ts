import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AuthSession } from '../api'


const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  getAuthSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  ...api,
}))

import { useAuthSession } from './useAuthSession'


function authenticatedSession(): AuthSession {
  return {
    required: true,
    authenticated: true,
    user_id: 'reader-1',
    username: 'reader',
    display_name: 'Reader',
    workspace_id: 'default',
    role: 'viewer',
    must_change_password: true,
    csrf_token: 'csrf',
    expires_at: '2099-01-01T00:00:00Z',
  }
}

describe('useAuthSession', () => {
  beforeEach(() => vi.clearAllMocks())

  it('改密已提交成功时，后续会话刷新失败不会误报为改密失败', async () => {
    api.changePassword.mockResolvedValue(undefined)
    api.getAuthSession.mockRejectedValue(new Error('network unavailable'))
    const auth = useAuthSession()
    auth.session.value = authenticatedSession()

    await auth.updatePassword('temporary password', 'permanent reader password')

    expect(api.changePassword).toHaveBeenCalledOnce()
    expect(api.getAuthSession).toHaveBeenCalledOnce()
    expect(auth.error.value).toBe('')
    expect(auth.notice.value).toContain('密码已更新')
    expect(auth.session.value).toMatchObject({ required: true, authenticated: false })
    expect(auth.requiresLogin.value).toBe(true)
    expect(auth.submitting.value).toBe(false)
  })
})
