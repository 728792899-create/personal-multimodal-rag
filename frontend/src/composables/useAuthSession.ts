import { computed, ref } from 'vue'

import { changePassword, getAuthSession, login, logout, type AuthSession } from '../api'
import { localizedSystemText } from '../localization'


export function useAuthSession() {
  const session = ref<AuthSession | null>(null)
  const loading = ref(true)
  const submitting = ref(false)
  const error = ref('')
  const notice = ref('')
  const requiresLogin = computed(() => Boolean(session.value?.required && !session.value.authenticated))
  const requiresPasswordChange = computed(() => Boolean(
    session.value?.authenticated && session.value.must_change_password,
  ))

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      session.value = await getAuthSession()
    } catch (caught) {
      error.value = localizedSystemText(caught instanceof Error ? caught.message : '', '无法检查登录状态')
    } finally {
      loading.value = false
    }
  }

  async function signIn(username: string, password: string) {
    submitting.value = true
    error.value = ''
    notice.value = ''
    try {
      session.value = await login(username, password)
    } catch (caught) {
      error.value = localizedSystemText(caught instanceof Error ? caught.message : '', '登录失败')
    } finally {
      submitting.value = false
    }
  }

  async function updatePassword(currentPassword: string, newPassword: string) {
    submitting.value = true
    error.value = ''
    notice.value = ''
    try {
      await changePassword(currentPassword, newPassword)
    } catch (caught) {
      error.value = localizedSystemText(caught instanceof Error ? caught.message : '', '修改密码失败')
      submitting.value = false
      return
    }

    // The password endpoint commits the change and revokes the current
    // session atomically. Reflect that state before the follow-up read so a
    // transient refresh failure can never be presented as a password failure.
    session.value = unauthenticatedSession(session.value?.required ?? true)
    notice.value = '密码已更新，请使用新密码重新登录。'
    try {
      session.value = await getAuthSession()
    } catch {
      // Keep the known signed-out state. The login screen remains usable and
      // a later login/session refresh will reconcile the server state.
    }
    submitting.value = false
  }

  async function signOut() {
    submitting.value = true
    try {
      await logout()
      session.value = await getAuthSession()
    } finally {
      submitting.value = false
    }
  }

  return {
    session,
    loading,
    submitting,
    error,
    notice,
    requiresLogin,
    requiresPasswordChange,
    refresh,
    signIn,
    updatePassword,
    signOut,
  }
}


function unauthenticatedSession(required: boolean): AuthSession {
  return {
    required,
    authenticated: false,
    user_id: '',
    username: '',
    display_name: '',
    workspace_id: '',
    role: '',
    must_change_password: false,
    csrf_token: '',
    expires_at: '',
  }
}
