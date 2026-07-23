import { computed, ref } from 'vue'

import { getAuthSession, login, logout, type AuthSession } from '../api'


export function useAuthSession() {
  const session = ref<AuthSession | null>(null)
  const loading = ref(true)
  const submitting = ref(false)
  const error = ref('')
  const requiresLogin = computed(() => Boolean(session.value?.required && !session.value.authenticated))

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      session.value = await getAuthSession()
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法检查登录状态'
    } finally {
      loading.value = false
    }
  }

  async function signIn(password: string) {
    submitting.value = true
    error.value = ''
    try {
      session.value = await login(password)
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '登录失败'
    } finally {
      submitting.value = false
    }
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
    requiresLogin,
    refresh,
    signIn,
    signOut,
  }
}
