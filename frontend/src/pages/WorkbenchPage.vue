<script setup lang="ts">
import { onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'

import AnswerExperience from '../components/AnswerExperience.vue'
import AppHeader from '../components/AppHeader.vue'
import InspectorPanel from '../components/InspectorPanel.vue'
import KnowledgePanel from '../components/KnowledgePanel.vue'
import ModelConnectionPanel from '../components/ModelConnectionPanel.vue'
import QueryWorkspace from '../components/QueryWorkspace.vue'
import type { ProviderStatus } from '../api'
import { useWorkbench } from '../composables/useWorkbench'
import { workbenchKey } from '../composables/workbenchContext'

const props = withDefaults(defineProps<{
  canManageProviders?: boolean
  showLogout?: boolean
  signingOut?: boolean
}>(), {
  canManageProviders: false,
  showLogout: false,
  signingOut: false,
})
const emit = defineEmits<{
  signOut: []
}>()
const workbench = useWorkbench()
const libraryOpen = ref(false)
const inspectorOpen = ref(false)
const modelConnectionOpen = ref(false)
let lastDrawerTrigger: HTMLElement | null = null
provide(workbenchKey, workbench)

function focusQuestion() {
  document.querySelector<HTMLTextAreaElement>('textarea[name="question"]')?.focus()
}

function openLibrary() {
  lastDrawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  libraryOpen.value = true
  inspectorOpen.value = false
  modelConnectionOpen.value = false
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('.library-drawer .drawer-close')?.focus()
  })
}

function openInspector() {
  lastDrawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  inspectorOpen.value = true
  libraryOpen.value = false
  modelConnectionOpen.value = false
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('.inspector-drawer .drawer-close')?.focus()
  })
}

function openModelConnection() {
  lastDrawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  modelConnectionOpen.value = true
  libraryOpen.value = false
  inspectorOpen.value = false
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('.model-connection-drawer .drawer-close')?.focus()
  })
}

function switchLibraryToInspector() {
  inspectorOpen.value = true
  libraryOpen.value = false
  modelConnectionOpen.value = false
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('.inspector-drawer .drawer-close')?.focus()
  })
}

function closeDrawers(returnFocus = true) {
  const trigger = lastDrawerTrigger
  libraryOpen.value = false
  inspectorOpen.value = false
  modelConnectionOpen.value = false
  if (returnFocus) {
    requestAnimationFrame(() => trigger?.focus())
  }
  lastDrawerTrigger = null
}

function onGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && (libraryOpen.value || inspectorOpen.value || modelConnectionOpen.value)) {
    event.preventDefault()
    closeDrawers()
    return
  }
  if (event.key === 'Tab' && (libraryOpen.value || inspectorOpen.value || modelConnectionOpen.value)) {
    const drawer = document.querySelector<HTMLElement>(
      libraryOpen.value
        ? '.library-drawer.open'
        : inspectorOpen.value
          ? '.inspector-drawer.open'
          : '.model-connection-drawer.open',
    )
    const focusable = drawer
      ? Array.from(drawer.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex]:not([tabindex="-1"])',
        ))
      : []
    if (focusable.length) {
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }
  const target = event.target
  const isTyping = target instanceof HTMLElement
    && target.matches('input, textarea, select, [contenteditable="true"]')
  if ((!isTyping && event.key === '/') || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k')) {
    event.preventDefault()
    closeDrawers(false)
    focusQuestion()
  }
}

function closeInspectorAndFocusQuestion() {
  closeDrawers(false)
  requestAnimationFrame(focusQuestion)
}

watch([libraryOpen, inspectorOpen, modelConnectionOpen], ([library, inspector, modelConnection]) => {
  document.body.classList.toggle('workbench-drawer-open', library || inspector || modelConnection)
})

onMounted(() => {
  workbench.boot()
  document.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onGlobalKeydown)
  document.body.classList.remove('workbench-drawer-open')
})
</script>

<template>
  <div :class="['app-shell', `app-mode-${workbench.appMode.value}`]">
    <a class="skip-link" href="#main-workspace">跳到主要内容</a>
    <AppHeader
      :show-logout="props.showLogout"
      :signing-out="props.signingOut"
      :library-open="libraryOpen"
      :inspector-open="inspectorOpen"
      :model-connection-open="modelConnectionOpen"
      @open-library="openLibrary"
      @open-inspector="openInspector"
      @open-model-connection="openModelConnection"
      @sign-out="emit('signOut')"
    />
    <main id="main-workspace" class="qa-workspace" tabindex="-1">
      <div id="conversation-workspace" class="qa-canvas">
        <AnswerExperience @open-inspector="openInspector" />
        <QueryWorkspace />
      </div>
    </main>

    <button
      v-if="libraryOpen || inspectorOpen || modelConnectionOpen"
      type="button"
      class="drawer-backdrop"
      aria-label="关闭侧边面板"
      @click="closeDrawers()"
    ></button>

    <section
      :class="['workspace-drawer', 'library-drawer', { open: libraryOpen }]"
      :aria-hidden="!libraryOpen"
      :inert="!libraryOpen"
      role="dialog"
      aria-modal="true"
      aria-labelledby="library-drawer-title"
    >
      <header class="drawer-heading">
        <div>
          <span>知识来源</span>
          <h2 id="library-drawer-title">资料库</h2>
        </div>
        <button type="button" class="drawer-close" aria-label="关闭资料库" @click="closeDrawers()">×</button>
      </header>
      <KnowledgePanel @open-inspector="switchLibraryToInspector" />
    </section>

    <section
      :class="['workspace-drawer', 'inspector-drawer', { open: inspectorOpen }]"
      :aria-hidden="!inspectorOpen"
      :inert="!inspectorOpen"
      role="dialog"
      aria-modal="true"
      aria-labelledby="inspector-drawer-title"
    >
      <header class="drawer-heading">
        <div>
          <span>检索诊断</span>
          <h2 id="inspector-drawer-title">证据与调试</h2>
        </div>
        <button type="button" class="drawer-close" aria-label="关闭检索调试" @click="closeDrawers()">×</button>
      </header>
      <InspectorPanel @focus-question="closeInspectorAndFocusQuestion" />
    </section>

    <section
      id="model-connection-drawer"
      :class="['workspace-drawer', 'model-connection-drawer', { open: modelConnectionOpen }]"
      :aria-hidden="!modelConnectionOpen"
      :inert="!modelConnectionOpen"
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-connection-drawer-title"
    >
      <header class="drawer-heading">
        <div>
          <span>临时模型连接</span>
          <h2 id="model-connection-drawer-title">连接 DeepSeek</h2>
        </div>
        <button type="button" class="drawer-close" aria-label="关闭模型连接" @click="closeDrawers()">×</button>
      </header>
      <ModelConnectionPanel
        :can-manage-providers="props.canManageProviders"
        :provider-status="workbench.providerStatus.value"
        :open="modelConnectionOpen"
        @status-change="(status: ProviderStatus) => { workbench.providerStatus.value = status }"
      />
    </section>

    <nav class="mobile-workspace-nav" aria-label="移动端工作台导航">
      <button type="button" @click="workbench.startNewConversation"><span aria-hidden="true">＋</span>新对话</button>
      <button type="button" @click="openLibrary"><span aria-hidden="true">□</span>资料</button>
      <button type="button" @click="openInspector"><span aria-hidden="true">⌁</span>调试</button>
      <button
        type="button"
        :aria-expanded="modelConnectionOpen"
        aria-controls="model-connection-drawer"
        @click="openModelConnection"
      >模型</button>
    </nav>
  </div>
</template>
