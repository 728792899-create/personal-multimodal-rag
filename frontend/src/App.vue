<script setup lang="ts">
import { computed, onMounted } from 'vue'

import WorkbenchPage from './pages/WorkbenchPage.vue'
import LoginPage from './pages/LoginPage.vue'
import ChangePasswordPage from './pages/ChangePasswordPage.vue'
import { useAuthSession } from './composables/useAuthSession'

const auth = useAuthSession()
const {
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
} = auth
const sessionCheckFailed = computed(() => !loading.value && !session.value && Boolean(error.value))
onMounted(refresh)
</script>

<template>
  <div v-if="loading" class="app-loading" role="status">正在检查工作区会话…</div>
  <main v-else-if="sessionCheckFailed" class="app-session-error">
    <section role="alert" aria-labelledby="session-error-title">
      <p class="kicker">工作区暂不可用</p>
      <h1 id="session-error-title">无法确认工作区会话</h1>
      <p>{{ error }}</p>
      <button class="button primary" type="button" @click="refresh">重试连接</button>
    </section>
  </main>
  <LoginPage
    v-else-if="requiresLogin"
    :submitting="submitting"
    :error="error"
    :notice="notice"
    @submit="signIn"
  />
  <ChangePasswordPage
    v-else-if="requiresPasswordChange"
    :username="session?.username || ''"
    :submitting="submitting"
    :error="error"
    @submit="updatePassword"
    @sign-out="signOut"
  />
  <WorkbenchPage
    v-else
    :can-manage-providers="Boolean(
      session?.required
      && session?.authenticated
      && ['owner', 'admin'].includes(session?.role || '')
    )"
    :can-manage-members="session?.role === 'admin'"
    :current-user="session || null"
    :show-logout="Boolean(session?.required)"
    :signing-out="submitting"
    @session-changed="refresh"
    @sign-out="signOut"
  />
</template>
