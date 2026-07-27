<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { exportConversationUrl, exportKnowledgeCardUrl } from '../api'
import { useWorkbenchContext } from '../composables/workbenchContext'
import {
  localizedSystemText,
  localizedIndexStage,
  localizedSourceType,
  localizedStatus,
} from '../localization'
import SourceManager from './SourceManager.vue'

const workbench = useWorkbenchContext()
const emit = defineEmits<{
  openInspector: []
}>()
const fileInput = ref<HTMLInputElement | null>(null)
const visibleDocumentLimit = ref(40)
const visibleDocuments = computed(() => workbench.filteredDocuments.value.slice(0, visibleDocumentLimit.value))
const remainingDocumentCount = computed(
  () => Math.max(0, workbench.filteredDocuments.value.length - visibleDocumentLimit.value),
)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  workbench.selectedFile.value = input.files?.[0] ?? null
}

function onFileDrop(event: DragEvent) {
  workbench.selectedFile.value = event.dataTransfer?.files?.[0] ?? null
}

async function openDocument(documentId: string) {
  if (await workbench.selectDocument(documentId)) emit('openInspector')
}

function qualityLabel(score?: number) {
  if (score === undefined) return '待评估'
  if (score >= 85) return '优秀'
  if (score >= 70) return '可用'
  return '需复核'
}

function onKnowledgeBaseChange(event: Event) {
  workbench.selectKnowledgeBase((event.target as HTMLSelectElement).value)
}

watch(
  () => workbench.selectedFile.value,
  (file) => {
    if (!file && fileInput.value) fileInput.value.value = ''
  },
)

watch(
  () => [workbench.documentFilter.value, workbench.selectedKnowledgeBaseId.value],
  () => {
    visibleDocumentLimit.value = 40
  },
)
</script>

<template>
  <aside class="surface knowledge-panel" aria-labelledby="knowledge-title">
    <header class="section-heading">
      <div class="section-identity">
        <span class="section-index" aria-hidden="true">资料</span>
        <div>
          <p class="kicker">证据资料库</p>
          <h2 id="knowledge-title">知识与会话</h2>
        </div>
      </div>
      <button
        v-if="workbench.scopedDocumentIds.value.length"
        type="button"
        class="button text-button"
        @click="workbench.clearScope"
      >
        清除范围
      </button>
    </header>

    <section class="knowledge-base-switcher" aria-labelledby="knowledge-base-title">
      <div class="switcher-heading">
        <label id="knowledge-base-title" for="knowledge-base-select">当前知识库</label>
        <span>{{ workbench.documents.value.length }} 份资料</span>
      </div>
      <select
        id="knowledge-base-select"
        :value="workbench.selectedKnowledgeBaseId.value"
        :disabled="workbench.loadingKnowledgeBases.value"
        @change="onKnowledgeBaseChange"
      >
        <option v-for="item in workbench.knowledgeBases.value" :key="item.id" :value="item.id">
          {{ item.name }}（{{ item.document_count }}）
        </option>
      </select>
      <form class="inline-create" aria-label="创建知识库" @submit.prevent="workbench.addKnowledgeBase">
        <input v-model="workbench.newKnowledgeBaseName.value" maxlength="120" placeholder="新知识库名称" />
        <button class="button secondary-button" type="submit" :disabled="!workbench.newKnowledgeBaseName.value.trim()">新增</button>
      </form>
    </section>

    <section class="ingest-group" aria-labelledby="upload-title">
      <h3 id="upload-title" class="sr-only">上传文件</h3>
      <label
        class="file-drop"
        :class="{ selected: workbench.selectedFile.value }"
        @dragenter.prevent
        @dragover.prevent
        @drop.prevent="onFileDrop"
      >
        <span class="file-icon" aria-hidden="true"><i></i></span>
        <span>
          <strong>{{ workbench.selectedFile.value?.name || '拖入或选择资料' }}</strong>
          <small>PDF、DOCX、Markdown、文本或图片 · 最大 20 MB</small>
        </span>
        <input
          ref="fileInput"
          data-testid="file-input"
          type="file"
          accept=".pdf,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg"
          @change="onFileChange"
        />
      </label>
      <button
        type="button"
        class="button primary-button full-width"
        data-testid="upload-button"
        :disabled="!workbench.selectedFile.value || workbench.uploading.value"
        @click="workbench.handleUpload"
      >
        {{ workbench.uploading.value ? '正在解析并索引…' : '加入证据库' }}
      </button>
    </section>

    <form class="url-form" aria-label="导入网页资料" @submit.prevent="workbench.handleImportUrl">
      <label for="url-import">从网页采集证据</label>
      <div class="field-action">
        <input
          id="url-import"
          v-model="workbench.urlToImport.value"
          data-testid="url-input"
          type="url"
          inputmode="url"
          autocomplete="url"
          placeholder="https://example.com/guide"
        />
        <button
          type="submit"
          class="button secondary-button"
          data-testid="url-import-button"
          :disabled="workbench.importingUrl.value || !workbench.urlToImport.value.trim()"
        >
          {{ workbench.importingUrl.value ? '导入中…' : '导入' }}
        </button>
      </div>
    </form>

    <details class="task-section" :open="Boolean(workbench.activeJobs.value.length)">
      <summary>索引任务 <span>{{ workbench.indexJobs.value.length }}</span></summary>
      <div v-if="workbench.indexJobs.value.length" class="task-list" aria-live="polite">
        <article v-for="job in workbench.indexJobs.value.slice(0, 6)" :key="job.id">
          <div>
            <strong>{{ job.source_name }}</strong>
            <span>{{ localizedIndexStage(job.stage) }} · {{ job.progress }}% · 第 {{ job.attempts }}/{{ job.max_attempts }} 次</span>
          </div>
          <progress :value="job.progress" max="100">{{ job.progress }}%</progress>
          <p v-if="job.error_message" class="task-error">{{ localizedSystemText(job.error_message, '索引任务失败，请重试。') }}</p>
          <div class="inline-actions">
            <button
              v-if="['queued', 'running', 'cancelling'].includes(job.status)"
              type="button"
              class="button text-button"
              @click="workbench.cancelIndexJob(job.id)"
            >取消</button>
            <button
              v-if="['failed', 'cancelled'].includes(job.status)"
              type="button"
              class="button text-button"
              @click="workbench.retryIndexJob(job.id)"
            >重试</button>
            <span :class="['job-status', job.status]">{{ localizedStatus(job.status) }}</span>
          </div>
        </article>
      </div>
      <p v-else class="muted-copy">上传和 URL 导入会在这里显示可恢复进度。</p>
    </details>

    <SourceManager />

    <div class="list-toolbar">
      <label for="document-filter" class="sr-only">筛选文档</label>
      <input
        id="document-filter"
        v-model="workbench.documentFilter.value"
        type="search"
        placeholder="搜索知识库资料"
      />
      <button
        type="button"
        class="button icon-button"
        aria-label="重建全部索引"
        :disabled="!workbench.documents.value.length || workbench.rebuildingId.value === 'all'"
        @click="workbench.rebuildAll"
      >
        ↻
      </button>
    </div>

    <div v-if="workbench.booting.value" class="loading-block" aria-live="polite">
      <span class="spinner" aria-hidden="true"></span>
      正在加载知识库…
    </div>
    <div v-else-if="!workbench.filteredDocuments.value.length" class="empty-state compact-empty">
      <strong>{{ workbench.documentFilter.value ? '没有匹配文档' : '知识库还是空的' }}</strong>
      <p>{{ workbench.documentFilter.value ? '清除筛选条件后重试。' : '上传文件或导入公开 URL 开始构建证据。' }}</p>
    </div>
    <ul v-else class="document-list" aria-label="知识库文档">
      <li v-for="doc in visibleDocuments" :key="doc.id" :class="{ scoped: workbench.scopeSet.value.has(doc.id) }">
        <button
          type="button"
          class="scope-toggle"
          :aria-pressed="workbench.scopeSet.value.has(doc.id)"
          :aria-label="`${workbench.scopeSet.value.has(doc.id) ? '移出' : '加入'}检索范围：${doc.filename}`"
          @click="workbench.toggleScope(doc.id)"
        >
          <span aria-hidden="true"></span>
        </button>
        <button type="button" class="document-summary" @click="openDocument(doc.id)">
          <strong>{{ doc.filename }}</strong>
          <span>{{ localizedSourceType(doc.source_type) }} · {{ doc.chunk_count }} 片段</span>
          <small>{{ qualityLabel(doc.quality?.score) }} · 质量 {{ doc.quality?.score ?? '—' }}</small>
        </button>
        <div class="row-actions">
          <button
            type="button"
            class="button icon-button"
            :aria-label="`重建 ${doc.filename}`"
            :disabled="Boolean(workbench.rebuildingId.value)"
            @click="workbench.rebuildOne(doc.id)"
          >↻</button>
          <button
            type="button"
            class="button icon-button danger-button"
            :aria-label="`删除 ${doc.filename}`"
            @click="workbench.removeDocument(doc.id)"
          >×</button>
        </div>
      </li>
    </ul>
    <button
      v-if="remainingDocumentCount"
      type="button"
      class="button text-button full-width document-load-more"
      @click="visibleDocumentLimit += 40"
    >
      再显示 {{ Math.min(40, remainingDocumentCount) }} 份资料
    </button>

    <details class="conversation-section">
      <summary>持久化会话 <span>{{ workbench.conversations.value.length }}</span></summary>
      <button type="button" class="button secondary-button full-width new-conversation" @click="workbench.startNewConversation">
        新建会话
      </button>
      <div v-if="workbench.conversations.value.length" class="conversation-list">
        <article
          v-for="conversation in workbench.conversations.value.slice(0, 8)"
          :key="conversation.id"
          :class="{ active: conversation.id === workbench.activeConversationId.value }"
        >
          <button type="button" @click="workbench.selectConversation(conversation.id)">
            <strong>{{ conversation.title }}</strong>
            <span>{{ conversation.message_count }} 条消息 · {{ conversation.updated_at.slice(0, 10) }}</span>
          </button>
          <button type="button" class="button icon-button danger-button" :aria-label="`删除会话 ${conversation.title}`" @click="workbench.removeConversation(conversation.id)">×</button>
          <a
            class="button icon-button"
            :href="exportConversationUrl(conversation.id)"
            :aria-label="`导出会话 ${conversation.title}`"
            download
          >↓</a>
        </article>
      </div>
      <p v-else class="muted-copy">第一次提问时会创建本地持久化会话。</p>
    </details>

    <details class="history-section">
      <summary>知识卡片 <span>{{ workbench.cards.value.length }}</span></summary>
      <div v-if="workbench.cards.value.length" class="history-list">
        <a
          v-for="card in workbench.cards.value.slice(0, 8)"
          :key="card.id"
          class="export-row"
          :href="exportKnowledgeCardUrl(card.id)"
          download
        >
          <strong>{{ card.title }}</strong>
          <span>导出 Markdown</span>
        </a>
      </div>
      <p v-else class="muted-copy">从可信回答保存卡片后可在这里导出。</p>
    </details>

    <details class="history-section">
      <summary>问答历史 <span>{{ workbench.history.value.length }}</span></summary>
      <div v-if="workbench.history.value.length" class="history-list">
        <button
          v-for="item in workbench.history.value.slice(0, 8)"
          :key="item.id"
          type="button"
          @click="workbench.useHistory(item)"
        >
          <strong>{{ item.question }}</strong>
          <span>{{ item.created_at?.slice(0, 10) }}</span>
        </button>
        <button type="button" class="button text-button" @click="workbench.eraseHistory">清空历史</button>
      </div>
      <p v-else class="muted-copy">完成问答后会保留最近记录。</p>
    </details>
  </aside>
</template>
