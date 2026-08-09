<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { useSourceSync } from '../composables/useSourceSync'
import { useWorkbenchContext } from '../composables/workbenchContext'
import type { SourceType } from '../api'
import { localizedSourceType, localizedStatus, localizedSystemText } from '../localization'

const workbench = useWorkbenchContext()
const state = useSourceSync()
const type = ref<SourceType>('url_list')
const name = ref('')
const urls = ref('')
const feedUrl = ref('')
const rootId = ref('')
const relativePath = ref('')
const recursive = ref(true)

async function refresh() {
  await state.refresh(workbench.selectedKnowledgeBaseId.value)
  if (!rootId.value) rootId.value = state.capabilities.value.directory_roots[0]?.id || ''
}

async function create() {
  const config: Record<string, unknown> = type.value === 'url_list'
    ? { urls: urls.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) }
    : type.value === 'rss_atom'
      ? { feed_url: feedUrl.value.trim() }
      : { root_id: rootId.value, relative_path: relativePath.value.trim(), recursive: recursive.value }
  await state.add(
    type.value,
    name.value.trim(),
    workbench.selectedKnowledgeBaseId.value,
    config,
  )
  name.value = ''
  urls.value = ''
  feedUrl.value = ''
  relativePath.value = ''
}

async function sync(sourceId: string) {
  await state.run(sourceId, workbench.selectedKnowledgeBaseId.value)
  await workbench.boot()
}

async function remove(sourceId: string) {
  if (!window.confirm('删除订阅配置？已索引文档不会被自动删除。')) return
  await state.remove(sourceId, workbench.selectedKnowledgeBaseId.value)
}

async function confirmDeletion(sourceId: string) {
  if (!window.confirm('确认删除这些连续两次未出现的来源条目及其索引文档？')) return
  await state.confirm(sourceId, workbench.selectedKnowledgeBaseId.value)
  await workbench.boot()
}

watch(workbench.selectedKnowledgeBaseId, refresh)
onMounted(refresh)
</script>

<template>
  <details class="source-section" data-testid="source-manager">
    <summary>持续数据源 <span>{{ state.sources.value.length }}</span></summary>
    <p class="muted-copy">目录、URL 列表与 RSS/Atom 采用增量同步；空结果不会批量删除。</p>

    <form class="source-create" aria-label="添加持续数据源" @submit.prevent="create">
      <label>
        类型
        <select v-model="type" name="source-type">
          <option value="url_list">URL 列表</option>
          <option value="rss_atom">RSS / Atom</option>
          <option value="local_directory" :disabled="!state.capabilities.value.directory_roots.length">本地目录</option>
        </select>
      </label>
      <label>
        名称
        <input v-model="name" name="source-name" maxlength="160" required placeholder="产品文档订阅" />
      </label>
      <label v-if="type === 'url_list'">
        URL（每行一个）
        <textarea v-model="urls" name="source-urls" rows="3" required placeholder="https://example.com/guide"></textarea>
      </label>
      <label v-else-if="type === 'rss_atom'">
        订阅 URL
        <input v-model="feedUrl" name="source-feed-url" type="url" required placeholder="https://example.com/feed.xml" />
      </label>
      <template v-else>
        <label>
          允许的目录根
          <select v-model="rootId" name="source-root" required>
            <option v-for="root in state.capabilities.value.directory_roots" :key="root.id" :value="root.id">{{ root.label }}</option>
          </select>
        </label>
        <label>
          相对目录
          <input v-model="relativePath" name="source-relative-path" placeholder="研究笔记" />
        </label>
        <label class="checkbox-label">
          <input v-model="recursive" type="checkbox" />
          递归扫描子目录
        </label>
      </template>
      <button
        class="button secondary-button full-width"
        type="submit"
        :disabled="state.loading.value || !name.trim()"
      >
        {{ state.loading.value ? '正在保存…' : '添加数据源' }}
      </button>
    </form>

    <p v-if="state.error.value" class="task-error" role="alert">
      {{ localizedSystemText(state.error.value, '数据源操作失败，请重试。') }}
      <button class="button text-button" type="button" @click="refresh">重试</button>
    </p>
    <div v-if="state.sources.value.length" class="source-list" aria-live="polite">
      <article v-for="source in state.sources.value" :key="source.id">
        <div>
          <strong>{{ source.name }}</strong>
          <span>{{ localizedSourceType(source.type) }} · {{ source.item_count }} 条</span>
        </div>
        <p v-if="state.latestRuns.value.get(source.id)" class="source-run-summary">
          最近同步：{{ localizedStatus(state.latestRuns.value.get(source.id)?.status) }}
          · 新增/更新 {{ state.latestRuns.value.get(source.id)?.updated }}
          · 未变化 {{ state.latestRuns.value.get(source.id)?.unchanged }}
          · 失败 {{ state.latestRuns.value.get(source.id)?.failed }}
        </p>
        <p v-if="source.deletion_candidate_count" class="task-error">
          {{ source.deletion_candidate_count }} 条已连续两次消失，等待确认删除。
        </p>
        <div class="inline-actions">
          <button
            class="button text-button"
            type="button"
            :disabled="Boolean(state.busySourceId.value)"
            @click="sync(source.id)"
          >{{ state.busySourceId.value === source.id ? '同步中…' : '立即同步' }}</button>
          <button
            v-if="source.deletion_candidate_count"
            class="button text-button"
            type="button"
            @click="confirmDeletion(source.id)"
          >确认删除候选</button>
          <button class="button text-button danger-button" type="button" @click="remove(source.id)">删除订阅</button>
        </div>
      </article>
    </div>
    <p v-else-if="!state.loading.value" class="muted-copy">尚未添加持续数据源。</p>
  </details>
</template>
