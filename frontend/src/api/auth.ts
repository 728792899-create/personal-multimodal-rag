import { apiRequest, jsonBody, setCsrfToken } from './client'
import type { AuthSession } from './types'


export async function getAuthSession(): Promise<AuthSession> {
  const response = await apiRequest<{ session: AuthSession }>('/api/auth/session')
  setCsrfToken(response.session.csrf_token || '')
  return response.session
}

export async function login(password: string): Promise<AuthSession> {
  const response = await apiRequest<{ session: AuthSession }>(
    '/api/auth/login',
    { method: 'POST', ...jsonBody({ password }) },
  )
  setCsrfToken(response.session.csrf_token)
  return response.session
}

export async function logout(): Promise<void> {
  await apiRequest('/api/auth/logout', { method: 'POST' })
  setCsrfToken('')
}
