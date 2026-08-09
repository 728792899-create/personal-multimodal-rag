import { apiRequest, jsonBody, setCsrfToken } from './client'
import type { AuthSession, WorkspaceMember } from './types'


export async function getAuthSession(): Promise<AuthSession> {
  const response = await apiRequest<{ session: AuthSession }>('/api/auth/session')
  setCsrfToken(response.session.csrf_token || '')
  return response.session
}

export async function login(username: string, password: string): Promise<AuthSession> {
  const response = await apiRequest<{ session: AuthSession }>(
    '/api/auth/login',
    { method: 'POST', ...jsonBody({ username, password }) },
  )
  setCsrfToken(response.session.csrf_token)
  return response.session
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiRequest('/api/auth/password', {
    method: 'POST',
    ...jsonBody({ current_password: currentPassword, new_password: newPassword }),
  })
  setCsrfToken('')
}

export async function listMembers(): Promise<WorkspaceMember[]> {
  const response = await apiRequest<{ members: WorkspaceMember[] }>('/api/auth/members')
  return response.members
}

export async function createMember(payload: {
  username: string
  display_name: string
  role: WorkspaceMember['role']
  temporary_password: string
}): Promise<WorkspaceMember> {
  const response = await apiRequest<{ member: WorkspaceMember }>('/api/auth/members', {
    method: 'POST',
    ...jsonBody(payload),
  })
  return response.member
}

export async function updateMember(
  userId: string,
  payload: Partial<Pick<WorkspaceMember, 'display_name' | 'role' | 'is_active'>>,
): Promise<WorkspaceMember> {
  const response = await apiRequest<{ member: WorkspaceMember }>(`/api/auth/members/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    ...jsonBody(payload),
  })
  return response.member
}

export async function disableMember(userId: string): Promise<WorkspaceMember> {
  const response = await apiRequest<{ member: WorkspaceMember }>(`/api/auth/members/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
  return response.member
}

export async function resetMemberPassword(userId: string, temporaryPassword: string): Promise<WorkspaceMember> {
  const response = await apiRequest<{ member: WorkspaceMember }>(
    `/api/auth/members/${encodeURIComponent(userId)}/reset-password`,
    { method: 'POST', ...jsonBody({ temporary_password: temporaryPassword }) },
  )
  return response.member
}

export async function logout(): Promise<void> {
  await apiRequest('/api/auth/logout', { method: 'POST' })
  setCsrfToken('')
}
