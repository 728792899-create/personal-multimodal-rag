<script setup lang="ts">
import { onMounted, provide } from 'vue'

import AnswerExperience from '../components/AnswerExperience.vue'
import AppHeader from '../components/AppHeader.vue'
import InspectorPanel from '../components/InspectorPanel.vue'
import KnowledgePanel from '../components/KnowledgePanel.vue'
import QueryWorkspace from '../components/QueryWorkspace.vue'
import { useWorkbench } from '../composables/useWorkbench'
import { workbenchKey } from '../composables/workbenchContext'

const workbench = useWorkbench()
provide(workbenchKey, workbench)

onMounted(workbench.boot)
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-workspace">跳到主要内容</a>
    <AppHeader />
    <main id="main-workspace" class="workspace" tabindex="-1">
      <KnowledgePanel />
      <div class="main-column">
        <QueryWorkspace />
        <AnswerExperience />
      </div>
      <InspectorPanel />
    </main>
  </div>
</template>
