<script setup lang="ts">
import { useWorkbenchContext } from '../composables/workbenchContext'

const workbench = useWorkbenchContext()
</script>

<template>
  <header class="app-header">
    <div class="brand-lockup">
      <span class="brand-mark" aria-hidden="true">R</span>
      <div>
        <p class="kicker">Personal multimodal RAG</p>
        <h1>证据工作台</h1>
      </div>
    </div>

    <div class="mode-switch" role="group" aria-label="工作台模式">
      <button
        type="button"
        data-testid="mode-user"
        :aria-pressed="workbench.appMode.value === 'user'"
        @click="workbench.appMode.value = 'user'; workbench.workMode.value = 'answer'"
      >
        普通模式
      </button>
      <button
        type="button"
        data-testid="mode-expert"
        :aria-pressed="workbench.appMode.value === 'expert'"
        @click="workbench.appMode.value = 'expert'"
      >
        专家模式
      </button>
    </div>

    <dl class="header-metrics" aria-label="知识库概览">
      <div><dt>文档</dt><dd>{{ workbench.documents.value.length }}</dd></div>
      <div><dt>片段</dt><dd>{{ workbench.totalChunks.value }}</dd></div>
      <div><dt>质量</dt><dd>{{ workbench.avgQualityLabel.value }}</dd></div>
      <div><dt>范围</dt><dd>{{ workbench.scopeLabel.value }}</dd></div>
    </dl>
  </header>
</template>
