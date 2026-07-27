<script setup lang="ts">
import { computed, onMounted } from 'vue'

import WorkbenchPage from './pages/WorkbenchPage.vue'
import LoginPage from './pages/LoginPage.vue'
import { useAuthSession } from './composables/useAuthSession'

const auth = useAuthSession()
const {
  session,
  loading,
  submitting,
  error,
  requiresLogin,
  refresh,
  signIn,
  signOut,
} = auth
const sessionCheckFailed = computed(() => !loading.value && !session.value && Boolean(error.value))
onMounted(refresh)
</script>

<template>
  <div v-if="loading" class="app-loading" role="status">正在检查工作区会话…</div>
  <main v-else-if="sessionCheckFailed" class="app-session-error">
    <section role="alert" aria-labelledby="session-error-title">
      <p class="kicker">Workspace unavailable</p>
      <h1 id="session-error-title">无法确认工作区会话</h1>
      <p>{{ error }}</p>
      <button class="button primary" type="button" @click="refresh">重试连接</button>
    </section>
  </main>
  <LoginPage
    v-else-if="requiresLogin"
    :submitting="submitting"
    :error="error"
    @submit="signIn"
  />
  <WorkbenchPage
    v-else
    :show-logout="Boolean(session?.required)"
    :signing-out="submitting"
    @sign-out="signOut"
  />
</template>
