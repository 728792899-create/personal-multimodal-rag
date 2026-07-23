<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  submitting: boolean
  error: string
}>()

const emit = defineEmits<{
  submit: [password: string]
}>()
const password = ref('')

function handleSubmit() {
  if (password.value) emit('submit', password.value)
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="brand-mark" aria-hidden="true">R</div>
      <p class="kicker">Production Local</p>
      <h1 id="login-title">Personal Multimodal RAG</h1>
      <p class="login-copy">
        登录后进入自托管证据工作台。密码只发送到当前服务，不会写入浏览器存储。
      </p>
      <form @submit.prevent="handleSubmit">
        <label for="owner-password">管理员密码</label>
        <input
          id="owner-password"
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          :disabled="submitting"
          autofocus
          required
        >
        <p v-if="error" class="login-error" role="alert">{{ error }}</p>
        <button class="button primary" type="submit" :disabled="submitting || !password">
          {{ submitting ? '正在验证…' : '登录工作台' }}
        </button>
      </form>
      <p class="login-note">会话使用 HttpOnly Cookie；所有写操作还需 CSRF Token。</p>
    </section>
  </main>
</template>
