<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import {
  clearDeepSeekRuntime,
  connectDeepSeekRuntime,
  getProviderStatus,
  type DeepSeekRuntimeMutation,
  type DeepSeekRuntimeStatus,
  type ProviderStatus,
} from '../api'

const DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
const DEEPSEEK_MODEL = 'deepseek-v4-flash'

const props = defineProps<{
  canManageProviders: boolean
  providerStatus: ProviderStatus | null
  open: boolean
}>()
const emit = defineEmits<{
  statusChange: [status: ProviderStatus]
}>()

const apiKey = ref('')
const dataTransferConfirmed = ref(false)
const phase = ref<'idle' | 'loading' | 'success' | 'error'>('idle')
const message = ref('')
const refreshedProviderStatus = ref<ProviderStatus | null>(null)
const lastAction = ref<'connect' | 'clear' | 'refresh'>('connect')
const apiKeyInput = ref<HTMLInputElement | null>(null)
const statusRefreshing = ref(false)
let actionController: AbortController | null = null
let runtimeMutationVersion = 0

function runtimeActiveFor(status: ProviderStatus | null) {
  const runtime = status?.runtime?.deepseek
    || status?.providers.deepseek_runtime
    || null
  if (!runtime) return false
  if (typeof runtime.runtime_override === 'boolean') return runtime.runtime_override
  if (typeof runtime.active === 'boolean') return runtime.active
  if (typeof runtime.connected === 'boolean') return runtime.connected
  const state = String(runtime.status || runtime.health || '').toLowerCase()
  return ['ready', 'connected', 'active'].includes(state)
}

function serverDeepSeekReadyFor(status: ProviderStatus | null) {
  const answer = status?.providers.answer
  if (!answer) return false
  const provider = answer.provider.toLowerCase()
  const model = String(answer.model || '').toLowerCase()
  const baseUrl = String(answer.base_url || '').toLowerCase().replace(/\/+$/, '')
  const health = String(answer.health || '').toLowerCase()
  const identifiesDeepSeek = provider.includes('deepseek')
    || model.includes('deepseek')
    || baseUrl === DEEPSEEK_BASE_URL
  return identifiesDeepSeek
    && answer.configured
    && !['unavailable', 'failed', 'error'].includes(health)
}

const effectiveProviderStatus = computed(() => (
  refreshedProviderStatus.value || props.providerStatus
))
const runtimeActive = computed(() => runtimeActiveFor(effectiveProviderStatus.value))
const serverDeepSeekReady = computed(() => (
  serverDeepSeekReadyFor(effectiveProviderStatus.value)
))
const connected = computed(() => runtimeActive.value || serverDeepSeekReady.value)
const connectionLabel = computed(() => {
  if (runtimeActive.value) return '临时连接已启用'
  if (serverDeepSeekReady.value) return '服务端已连接'
  return '未连接'
})
const connectionNote = computed(() => {
  if (runtimeActive.value) return '输入新的 API 密钥可替换当前临时连接。'
  if (serverDeepSeekReady.value) {
    return '服务端已有 DeepSeek 配置；输入新密钥将仅在当前服务进程中临时替换。'
  }
  return '输入密钥后，将在当前服务进程中创建临时连接。'
})
const isLoading = computed(() => phase.value === 'loading')
const canConnect = computed(() => (
  props.canManageProviders
  && dataTransferConfirmed.value
  && !isLoading.value
  && apiKey.value.trim().length >= 8
))
const connectLabel = computed(() => {
  if (isLoading.value && lastAction.value === 'connect') return '正在验证…'
  if (runtimeActive.value) return '替换并验证'
  if (serverDeepSeekReady.value) return '临时替换并验证'
  return '连接并验证'
})
const inputDescriptionIds = computed(() => [
  'deepseek-security-note',
  'deepseek-data-transfer-note',
  'deepseek-connection-context',
  ...(!props.canManageProviders ? ['deepseek-permission-note'] : []),
].join(' '))

function safeError(error: unknown, action: 'connect' | 'clear') {
  const status = typeof error === 'object' && error && 'status' in error
    ? Number((error as { status?: number }).status)
    : 0
  if (status === 401) return '登录已失效，请重新登录后再试。'
  if (status === 403) return '会话校验失败，请刷新页面或重新登录后再试。'
  if (status === 408) return '连接验证超时，请稍后重试。'
  return action === 'clear'
    ? '临时连接清除失败，请重试。'
    : '连接验证失败，请检查网络和密钥后重试。'
}

async function refreshStatus() {
  const mutationVersionAtStart = runtimeMutationVersion
  const status = await getProviderStatus()
  if (mutationVersionAtStart === runtimeMutationVersion) {
    refreshedProviderStatus.value = status
    emit('statusChange', status)
  }
  return status
}

function statusFromMutation(mutation: DeepSeekRuntimeMutation) {
  const connection = mutation.connection || mutation.runtime?.deepseek
  if (!connection) return
  const connectionReady = connection.connected === true
    || connection.active === true
    || ['ready', 'connected', 'active'].includes(
      String(connection.status || connection.health || '').toLowerCase(),
    )
  const base: ProviderStatus = effectiveProviderStatus.value || {
    status: connectionReady ? 'ready' : 'degraded',
    environment: '当前服务',
    fallback_allowed: false,
    providers: {
      answer: {
        provider: 'template',
        configured: true,
        health: 'ready',
        mode: 'offline',
        capabilities: ['answer'],
      },
      embedding: {
        provider: 'unknown',
        configured: false,
        health: 'not_checked',
        mode: 'unknown',
        capabilities: [],
      },
      vector_store: {
        provider: 'unknown',
        configured: false,
        health: 'not_checked',
      },
    },
  }
  const answer = connectionReady
    ? {
        ...base.providers.answer,
        provider: 'deepseek_official',
        configured: true,
        health: connection.health || connection.status || 'ready',
        mode: 'external',
        capabilities: ['answer', 'stream'],
        model: connection.model || DEEPSEEK_MODEL,
        base_url: connection.base_url || DEEPSEEK_BASE_URL,
      }
    : {
        provider: 'template',
        configured: true,
        health: 'ready',
        mode: 'offline',
        capabilities: ['answer'],
      }
  const next: ProviderStatus = {
    ...base,
    runtime: {
      ...base.runtime,
      deepseek: connection,
    },
    providers: {
      ...base.providers,
      answer,
      deepseek_runtime: connection,
    },
  }
  refreshedProviderStatus.value = next
  emit('statusChange', next)
}

async function refreshWhenOpened() {
  if (!props.open) return
  statusRefreshing.value = true
  try {
    await refreshStatus()
  } catch {
    if (phase.value !== 'loading') {
      lastAction.value = 'refresh'
      phase.value = 'error'
      message.value = '当前连接状态刷新失败，请重试。'
    }
  } finally {
    statusRefreshing.value = false
  }
}

async function connect() {
  if (!canConnect.value) return
  actionController?.abort()
  actionController = new AbortController()
  const secret = apiKey.value.trim()
  apiKey.value = ''
  dataTransferConfirmed.value = false
  lastAction.value = 'connect'
  phase.value = 'loading'
  message.value = '正在验证临时连接…'
  try {
    const mutation = await connectDeepSeekRuntime(secret, {
      signal: actionController.signal,
      timeoutMs: 30_000,
    })
    runtimeMutationVersion += 1
    statusFromMutation(mutation)
    try {
      await refreshStatus()
    } catch {
      phase.value = 'success'
      message.value = '连接已生效但状态刷新失败。可以开始提问，稍后重新打开面板可再次检查状态。'
      return
    }
    phase.value = 'success'
    message.value = '临时连接验证通过，可以开始提问。'
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    phase.value = 'error'
    message.value = safeError(error, 'connect')
  }
}

async function clearConnection() {
  if (isLoading.value || !props.canManageProviders) return
  actionController?.abort()
  actionController = new AbortController()
  apiKey.value = ''
  dataTransferConfirmed.value = false
  lastAction.value = 'clear'
  phase.value = 'loading'
  message.value = '正在清除临时连接…'
  try {
    const mutation = await clearDeepSeekRuntime({ signal: actionController.signal })
    runtimeMutationVersion += 1
    statusFromMutation(mutation)
    let status: ProviderStatus
    try {
      status = await refreshStatus()
    } catch {
      phase.value = 'success'
      message.value = '清除已生效但状态刷新失败。稍后重新打开面板可再次检查状态。'
      return
    }
    phase.value = 'success'
    message.value = serverDeepSeekReadyFor(status)
      ? '已恢复服务端连接。'
      : '临时连接已清除。'
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    phase.value = 'error'
    message.value = safeError(error, 'clear')
  }
}

async function retry() {
  if (lastAction.value === 'clear') {
    await clearConnection()
    return
  }
  if (lastAction.value === 'refresh') {
    phase.value = 'idle'
    message.value = ''
    await refreshWhenOpened()
    return
  }
  phase.value = 'idle'
  message.value = ''
  await nextTick()
  apiKeyInput.value?.focus()
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      void refreshWhenOpened()
      return
    }
    apiKey.value = ''
    dataTransferConfirmed.value = false
  },
)

watch(() => props.providerStatus, () => {
  refreshedProviderStatus.value = null
})

onBeforeUnmount(() => actionController?.abort())
</script>

<template>
  <div class="model-connection-panel" :aria-busy="isLoading || statusRefreshing">
    <section class="model-connection-status" aria-labelledby="model-status-title">
      <div>
        <span id="model-status-title">当前状态</span>
        <strong>{{ connectionLabel }}</strong>
      </div>
      <i :class="{ connected }" aria-hidden="true"></i>
    </section>

    <dl class="model-connection-spec">
      <div>
        <dt>官方接口地址</dt>
        <dd>{{ DEEPSEEK_BASE_URL }}</dd>
      </div>
      <div>
        <dt>回答模型</dt>
        <dd>{{ DEEPSEEK_MODEL }}</dd>
      </div>
    </dl>

    <p id="deepseek-security-note" class="model-connection-note">
      密钥会发送到当前服务端，再由服务端转发到 DeepSeek 官方接口进行验证。密钥不会写入浏览器存储，也不会在页面回显。
    </p>

    <p id="deepseek-data-transfer-note" class="model-connection-disclosure">
      连接生效后，后续回答会把你的问题和检索命中的证据片段发送给 DeepSeek 生成回答。请只提交允许发送给第三方的内容。
    </p>

    <p id="deepseek-connection-context" class="model-connection-context">{{ connectionNote }}</p>

    <p
      v-if="!props.canManageProviders"
      id="deepseek-permission-note"
      class="model-connection-permission"
      role="note"
    >
      当前会话没有模型连接管理权限。请使用受保护的所有者或管理员会话登录后再操作。
    </p>

    <form class="model-connection-form" @submit.prevent="connect">
      <label for="deepseek-api-key">
        <span>接口密钥</span>
        <small>粘贴从 DeepSeek 控制台创建的密钥</small>
      </label>
      <input
        id="deepseek-api-key"
        ref="apiKeyInput"
        v-model="apiKey"
        data-testid="deepseek-api-key"
        type="password"
        name="deepseek-api-key"
        autocomplete="off"
        autocapitalize="none"
        spellcheck="false"
        minlength="8"
        placeholder="请输入接口密钥"
        :aria-describedby="inputDescriptionIds"
        :disabled="isLoading || !props.canManageProviders"
        required
      />
      <label class="model-connection-consent">
        <input
          v-model="dataTransferConfirmed"
          data-testid="deepseek-data-consent"
          type="checkbox"
          :disabled="isLoading || !props.canManageProviders"
          aria-describedby="deepseek-data-transfer-note"
        />
        <span>我已了解并同意上述数据发送方式</span>
      </label>
      <button
        type="submit"
        class="button primary model-connect-action"
        data-testid="connect-deepseek"
        :disabled="!canConnect"
      >
        {{ connectLabel }}
      </button>
    </form>

    <div v-if="runtimeActive" class="model-connected-actions">
      <p>当前回答优先使用临时连接；清除后将恢复服务端配置。</p>
      <button
        type="button"
        class="button danger-outline-button"
        data-testid="clear-deepseek"
        :disabled="isLoading || !props.canManageProviders"
        @click="clearConnection"
      >
        {{ isLoading && lastAction === 'clear' ? '正在清除…' : '清除临时连接' }}
      </button>
    </div>

    <p
      v-if="phase === 'error'"
      class="model-connection-message error"
      role="alert"
    >
      {{ message }}
    </p>
    <p
      v-else
      class="model-connection-message"
      role="status"
      aria-live="polite"
    >
      {{
        message
          || (runtimeActive
            ? '临时连接可用。'
            : serverDeepSeekReady
              ? '服务端连接可用。'
              : '等待输入密钥。')
      }}
    </p>

    <button
      v-if="phase === 'error'"
      type="button"
      class="button secondary model-retry-action"
      data-testid="retry-deepseek"
      :disabled="isLoading"
      @click="retry"
    >
      重试
    </button>
  </div>
</template>
