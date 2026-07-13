<script setup lang="ts">
import { useWorkbenchContext } from '../composables/workbenchContext'

const workbench = useWorkbenchContext()

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  workbench.selectedFile.value = input.files?.[0] ?? null
}

function qualityLabel(score?: number) {
  if (score === undefined) return '待评估'
  if (score >= 85) return '优秀'
  if (score >= 70) return '可用'
  return '需复核'
}
</script>

<template>
  <aside class="surface knowledge-panel" aria-labelledby="knowledge-title">
    <header class="section-heading">
      <div>
        <p class="kicker">Knowledge</p>
        <h2 id="knowledge-title">知识库</h2>
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

    <section class="ingest-group" aria-labelledby="upload-title">
      <h3 id="upload-title" class="sr-only">上传文件</h3>
      <label class="file-drop" :class="{ selected: workbench.selectedFile.value }">
        <span class="file-icon" aria-hidden="true">↑</span>
        <span>
          <strong>{{ workbench.selectedFile.value?.name || '选择文件' }}</strong>
          <small>PDF、Markdown、文本或图片 · 最大 20 MB</small>
        </span>
        <input
          data-testid="file-input"
          type="file"
          accept=".pdf,.md,.markdown,.txt,.png,.jpg,.jpeg"
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
        {{ workbench.uploading.value ? '正在解析并索引…' : '上传并索引' }}
      </button>
    </section>

    <form class="url-form" aria-label="导入网页资料" @submit.prevent="workbench.handleImportUrl">
      <label for="url-import">网页地址</label>
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

    <div class="list-toolbar">
      <label for="document-filter" class="sr-only">筛选文档</label>
      <input
        id="document-filter"
        v-model="workbench.documentFilter.value"
        type="search"
        placeholder="筛选文档"
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
      <li v-for="doc in workbench.filteredDocuments.value" :key="doc.id" :class="{ scoped: workbench.scopeSet.value.has(doc.id) }">
        <button
          type="button"
          class="scope-toggle"
          :aria-pressed="workbench.scopeSet.value.has(doc.id)"
          :aria-label="`${workbench.scopeSet.value.has(doc.id) ? '移出' : '加入'}检索范围：${doc.filename}`"
          @click="workbench.toggleScope(doc.id)"
        >
          <span aria-hidden="true"></span>
        </button>
        <button type="button" class="document-summary" @click="workbench.selectDocument(doc.id)">
          <strong>{{ doc.filename }}</strong>
          <span>{{ doc.source_type }} · {{ doc.chunk_count }} 片段</span>
          <small>{{ qualityLabel(doc.quality?.score) }} · Q {{ doc.quality?.score ?? '—' }}</small>
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
