<script setup lang="ts">
import { computed, ref } from 'vue'

import ProductMark from '../components/ProductMark.vue'

defineProps<{
  username: string
  submitting: boolean
  error: string
}>()

const emit = defineEmits<{
  submit: [currentPassword: string, newPassword: string]
  signOut: []
}>()

const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const localError = computed(() => {
  if (confirmation.value && confirmation.value !== newPassword.value) return '两次输入的新密码不一致。'
  if (newPassword.value && newPassword.value.length < 12) return '新密码至少需要 12 个字符。'
  if (currentPassword.value && newPassword.value === currentPassword.value) return '新密码不能与临时密码相同。'
  return ''
})
const canSubmit = computed(() => Boolean(
  currentPassword.value
  && newPassword.value.length >= 12
  && confirmation.value === newPassword.value
  && !localError.value,
))

function handleSubmit() {
  if (canSubmit.value) emit('submit', currentPassword.value, newPassword.value)
}
</script>

<template>
  <main class="login-page">
    <section class="login-stage password-change-stage" aria-labelledby="password-change-title">
      <aside class="login-identity" aria-label="安全提示">
        <header class="login-brand">
          <span class="brand-mark"><ProductMark /></span>
          <div><p class="kicker">账号安全</p><span class="login-wordmark">有据智能</span></div>
        </header>
        <div class="login-statement">
          <p class="login-index">01 / 首次登录</p>
          <h1>设置你的正式密码</h1>
          <p class="login-copy">临时密码只用于首次验证。更新后所有现有会话会立即撤销，需使用新密码重新登录。</p>
        </div>
      </aside>

      <section class="login-access" aria-labelledby="password-change-title">
        <header class="login-access-header">
          <p class="kicker">成员 {{ username }}</p>
          <h2 id="password-change-title">修改临时密码</h2>
          <p>新密码至少 12 个字符。</p>
        </header>
        <form class="login-form" @submit.prevent="handleSubmit">
          <div class="login-field-heading"><label for="current-password">临时密码</label><span>当前</span></div>
          <input id="current-password" v-model="currentPassword" type="password" autocomplete="current-password" :disabled="submitting" required>
          <div class="login-field-heading"><label for="new-password">新密码</label><span>至少 12 位</span></div>
          <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" minlength="12" :disabled="submitting" required>
          <div class="login-field-heading"><label for="confirm-password">确认新密码</label><span>再输入一次</span></div>
          <input id="confirm-password" v-model="confirmation" type="password" autocomplete="new-password" minlength="12" :disabled="submitting" required>
          <p v-if="localError || error" class="login-error" role="alert">{{ localError || error }}</p>
          <button class="button primary login-submit" type="submit" :disabled="submitting || !canSubmit">
            <span>{{ submitting ? '正在更新…' : '更新密码' }}</span><span aria-hidden="true">↗</span>
          </button>
          <button class="button secondary" type="button" :disabled="submitting" @click="emit('signOut')">退出账号</button>
        </form>
      </section>
    </section>
  </main>
</template>
