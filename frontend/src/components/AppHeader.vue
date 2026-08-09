<script setup lang="ts">
import { useWorkbenchContext } from '../composables/workbenchContext'
import { localizedProvider } from '../localization'
import ProductMark from './ProductMark.vue'

const workbench = useWorkbenchContext()
const props = withDefaults(defineProps<{
  showLogout?: boolean
  signingOut?: boolean
  libraryOpen?: boolean
  inspectorOpen?: boolean
  modelConnectionOpen?: boolean
}>(), {
  showLogout: false,
  signingOut: false,
  libraryOpen: false,
  inspectorOpen: false,
  modelConnectionOpen: false,
})
const emit = defineEmits<{
  signOut: []
  openLibrary: []
  openInspector: []
  openModelConnection: []
}>()
</script>

<template>
  <header class="app-header">
    <div class="command-brand">
      <span class="brand-mark"><ProductMark /></span>
      <div>
        <h1>知证</h1>
        <p>多模态知识问答</p>
      </div>
    </div>

    <nav class="primary-navigation" aria-label="主要导航">
      <a href="#conversation-workspace" aria-current="page">问答</a>
    </nav>

    <nav class="command-modes" aria-label="工作台视图">
      <div class="mode-switch" role="group" aria-label="工作台模式">
        <button
          type="button"
          data-testid="mode-user"
          :aria-pressed="workbench.appMode.value === 'user'"
          @click="workbench.appMode.value = 'user'; workbench.workMode.value = 'answer'"
        >
          简洁
        </button>
        <button
          type="button"
          data-testid="mode-expert"
          :aria-pressed="workbench.appMode.value === 'expert'"
          @click="workbench.appMode.value = 'expert'"
        >
          调试
        </button>
      </div>
    </nav>

    <div class="header-actions">
      <span
        v-if="workbench.appMode.value === 'expert' && workbench.providerStatus.value"
        :class="['provider-health', workbench.providerStatus.value.status]"
        :title="`${localizedProvider(workbench.providerStatus.value.providers.answer.provider)} · ${localizedProvider(workbench.providerStatus.value.providers.vector_store.provider)}`"
      >
        <i aria-hidden="true"></i>
        {{ workbench.providerStatus.value.status === 'ready' ? '服务就绪' : '服务降级' }}
      </span>
      <span
        v-else-if="workbench.appMode.value === 'expert'"
        class="provider-health pending"
      ><i aria-hidden="true"></i>正在检查服务</span>

      <button
        id="open-model-connection"
        type="button"
        class="header-tool model-connection-trigger"
        data-testid="open-model-connection"
        :aria-expanded="props.modelConnectionOpen"
        aria-controls="model-connection-drawer"
        @click="emit('openModelConnection')"
      >
        <span>模型连接</span>
      </button>
      <button
        id="open-library"
        type="button"
        class="header-tool"
        data-testid="open-library"
        :aria-expanded="props.libraryOpen"
        @click="emit('openLibrary')"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19a1 1 0 0 1 1 1v15.5a.5.5 0 0 1-.8.4 4 4 0 0 0-2.4-.9H6.5A2.5 2.5 0 0 1 4 16.5zM4 16.5A2.5 2.5 0 0 0 6.5 19"/><path d="M8 7h8M8 11h6"/></svg>
        <span>资料库</span>
      </button>
      <button
        id="open-inspector"
        type="button"
        class="header-tool"
        data-testid="open-inspector"
        :aria-expanded="props.inspectorOpen"
        @click="emit('openInspector')"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 18V9m5 9V5m6 13v-7m5 7V3"/><path d="M2 18h20"/></svg>
        <span>检索调试</span>
      </button>
      <button type="button" class="header-tool new-chat" aria-label="新建对话" @click="workbench.startNewConversation">
        <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
      </button>
    </div>

    <button
      v-if="props.showLogout"
      class="session-logout command-logout button secondary"
      type="button"
      aria-label="退出登录"
      :disabled="props.signingOut"
      @click="emit('signOut')"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M10 5H5v14h5M14 8l4 4-4 4M8 12h10"/></svg>
      <span class="sr-only">{{ props.signingOut ? '正在退出…' : '退出登录' }}</span>
    </button>
  </header>
</template>
