<script setup lang="ts">
import { ref } from 'vue'

import ProductMark from '../components/ProductMark.vue'

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
    <section class="login-stage" aria-labelledby="login-title">
      <aside class="login-identity" aria-label="产品简介">
        <header class="login-brand">
          <span class="brand-mark"><ProductMark /></span>
          <div>
            <p class="kicker">Evidence ledger · local</p>
            <span class="login-wordmark">Grounded intelligence</span>
          </div>
        </header>

        <div class="login-statement">
          <p class="login-index">01 / Evidence workspace</p>
          <h1 id="login-title">Personal Multimodal RAG</h1>
          <p class="login-thesis">把每个结论放回可检索、可引用、可审计的证据链中。</p>
          <p class="login-copy">
            面向单用户与小团队的自托管多模态知识工作台，覆盖解析、混合检索、图谱导航、拒答保护和离线评测。
          </p>
        </div>

        <dl class="login-ledger" aria-label="工作台核心能力">
          <div>
            <dt>01</dt>
            <dd>
              <strong>Hybrid retrieval</strong>
              <span>BM25、向量、MMR 与 rerank 形成可解释召回链路</span>
            </dd>
          </div>
          <div>
            <dt>02</dt>
            <dd>
              <strong>Evidence provenance</strong>
              <span>引用定位到文档元素，并保留相邻上下文与审计结果</span>
            </dd>
          </div>
          <div>
            <dt>03</dt>
            <dd>
              <strong>Local control</strong>
              <span>资料、会话与评测事实保留在当前部署边界内</span>
            </dd>
          </div>
        </dl>

        <footer class="login-identity-footer">
          <span>Production Local</span>
          <span>Single workspace</span>
          <span>0.4.0 RC</span>
        </footer>
      </aside>

      <section class="login-access" aria-labelledby="access-title">
        <div class="login-access-index" aria-hidden="true">OWNER / 01</div>
        <header class="login-access-header">
          <p class="kicker">Secure workspace</p>
          <h2 id="access-title">进入证据工作台</h2>
          <p>使用本机管理员凭据建立受保护会话。</p>
        </header>

        <form class="login-form" @submit.prevent="handleSubmit">
          <div class="login-field-heading">
            <label for="owner-password">管理员密码</label>
            <span>LOCAL SESSION</span>
          </div>
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
          <button class="button primary login-submit" type="submit" :disabled="submitting || !password">
            <span>{{ submitting ? '正在验证…' : '登录工作台' }}</span>
            <span aria-hidden="true">↗</span>
          </button>
        </form>

        <div class="login-security" aria-label="会话安全说明">
          <div>
            <span>SESSION</span>
            <strong>HttpOnly Cookie</strong>
          </div>
          <div>
            <span>WRITE ACCESS</span>
            <strong>CSRF protected</strong>
          </div>
        </div>
        <p class="login-note">
          密码只发送到当前服务，不会写入浏览器存储。所有写操作还需 CSRF Token。
        </p>
      </section>
    </section>
  </main>
</template>
