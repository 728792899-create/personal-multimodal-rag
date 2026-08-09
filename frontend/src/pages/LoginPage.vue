<script setup lang="ts">
import { ref } from 'vue'

import ProductMark from '../components/ProductMark.vue'
import { localizedSystemText } from '../localization'

defineProps<{
  submitting: boolean
  error: string
  notice?: string
}>()

const emit = defineEmits<{
  submit: [username: string, password: string]
}>()
const username = ref('')
const password = ref('')

function handleSubmit() {
  if (username.value && password.value) emit('submit', username.value, password.value)
}
</script>

<template>
  <main class="login-page">
    <section class="login-stage" aria-labelledby="login-title">
      <aside class="login-identity" aria-label="产品简介">
        <header class="login-brand">
          <span class="brand-mark"><ProductMark /></span>
          <div>
            <p class="kicker">证据账本 · 本地</p>
            <span class="login-wordmark">有据智能</span>
          </div>
        </header>

        <div class="login-statement">
          <p class="login-index">01 / 证据工作台</p>
          <h1 id="login-title">个人多模态 RAG</h1>
          <p class="login-thesis">把每个结论放回可检索、可引用、可审计的证据链中。</p>
          <p class="login-copy">
            面向单用户与小团队的自托管多模态知识工作台，覆盖解析、混合检索、图谱导航、拒答保护和离线评测。
          </p>
        </div>

        <dl class="login-ledger" aria-label="工作台核心能力">
          <div>
            <dt>01</dt>
            <dd>
              <strong>混合检索</strong>
              <span>BM25、向量、MMR 与重排序形成可解释召回链路</span>
            </dd>
          </div>
          <div>
            <dt>02</dt>
            <dd>
              <strong>证据溯源</strong>
              <span>引用定位到文档元素，并保留相邻上下文与审计结果</span>
            </dd>
          </div>
          <div>
            <dt>03</dt>
            <dd>
              <strong>本地控制</strong>
              <span>资料、会话与评测事实保留在当前部署边界内</span>
            </dd>
          </div>
        </dl>

        <footer class="login-identity-footer">
          <span>本地生产模式</span>
          <span>单一工作区</span>
          <span>1.0.0 候选版</span>
        </footer>
      </aside>

      <section class="login-access" aria-labelledby="access-title">
        <div class="login-access-index" aria-hidden="true">所有者 / 01</div>
        <header class="login-access-header">
          <p class="kicker">受保护工作区</p>
          <h2 id="access-title">进入证据工作台</h2>
          <p>使用内部成员账号建立受保护会话。</p>
        </header>

        <form class="login-form" @submit.prevent="handleSubmit">
          <p v-if="notice" class="login-note" role="status">{{ notice }}</p>
          <div class="login-field-heading">
            <label for="member-username">用户名</label>
            <span>内部成员</span>
          </div>
          <input
            id="member-username"
            v-model="username"
            name="username"
            type="text"
            autocomplete="username"
            :disabled="submitting"
            autofocus
            required
          >
          <div class="login-field-heading">
            <label for="owner-password">密码</label>
            <span>本地会话</span>
          </div>
          <input
            id="owner-password"
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            :disabled="submitting"
            required
          >
          <p v-if="error" class="login-error" role="alert">{{ localizedSystemText(error, '登录失败，请重试。') }}</p>
          <button class="button primary login-submit" type="submit" :disabled="submitting || !username || !password">
            <span>{{ submitting ? '正在验证…' : '登录工作台' }}</span>
            <span aria-hidden="true">↗</span>
          </button>
        </form>

        <div class="login-security" aria-label="会话安全说明">
          <div>
            <span>会话</span>
            <strong>仅 HTTP 可访问的会话令牌</strong>
          </div>
          <div>
            <span>写入权限</span>
            <strong>已启用 CSRF 防护</strong>
          </div>
        </div>
        <p class="login-note">
          密码只发送到当前服务，不会写入浏览器存储。所有写操作还需 CSRF 令牌。
        </p>
      </section>
    </section>
  </main>
</template>
