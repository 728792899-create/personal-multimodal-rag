<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { useWorkbenchContext } from '../composables/workbenchContext'
import { localizedCompareProfile } from '../localization'

const workbench = useWorkbenchContext()
const questionInput = ref<HTMLTextAreaElement | null>(null)

const presets = [
  '这个 RAG 系统的核心工程亮点是什么？',
  '这个系统如何通过引用和拒答机制降低幻觉？',
  '这份资料有没有提到 Kubernetes 部署？',
]

const modalities = [
  { id: 'text', label: '文本' },
  { id: 'image', label: '图像' },
  { id: 'table', label: '表格' },
  { id: 'equation', label: '公式' },
  { id: 'code', label: '代码' },
] as const

async function onQueryImages(event: Event) {
  const input = event.target as HTMLInputElement
  await workbench.addQueryAttachments(
    Array.from(input.files || []),
    workbench.selectedKnowledgeBaseId.value,
  )
  input.value = ''
}

function toggleModality(id: typeof modalities[number]['id']) {
  workbench.modalityFilters.value = workbench.modalityFilters.value.includes(id)
    ? workbench.modalityFilters.value.filter((item) => item !== id)
    : [...workbench.modalityFilters.value, id]
}

function resizeQuestion() {
  const input = questionInput.value
  if (!input) return
  input.style.height = 'auto'
  input.style.height = `${Math.min(Math.max(input.scrollHeight, 52), 190)}px`
}

watch(
  () => workbench.question.value,
  () => nextTick(resizeQuestion),
)
</script>

<template>
  <section class="query-workspace" aria-labelledby="query-title">
    <h2 id="query-title" class="sr-only">向知识库提问</h2>

    <section v-if="workbench.appMode.value === 'expert'" class="expert-controls" aria-labelledby="expert-title">
      <details open>
        <summary>
          <span>
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 18V9m5 9V5m6 13v-7m5 7V3"/><path d="M2 18h20"/></svg>
            检索参数
          </span>
          <small>BM25 {{ workbench.bm25Weight.value.toFixed(2) }} / 向量 {{ workbench.vectorWeight.value.toFixed(2) }}</small>
        </summary>
        <div class="expert-panel-body">
          <div class="expert-panel-heading">
            <div>
              <h3 id="expert-title">调试检索策略</h3>
              <p>仅影响本次查询。检索过程与引用证据可在右上角“检索调试”中查看。</p>
            </div>
            <button type="button" class="button text-button" @click="workbench.resetRetrievalControls">恢复默认</button>
          </div>
          <div class="control-grid">
            <label>
              <span>检索模式</span>
              <select v-model="workbench.searchMode.value" name="search-mode">
                <option value="hybrid">混合检索</option>
                <option value="keyword">仅 BM25</option>
                <option value="semantic">仅向量</option>
              </select>
            </label>
            <label>
              <span>检索配置</span>
              <select v-model="workbench.searchProfile.value" name="search-profile">
                <option value="balanced">均衡</option>
                <option value="precision">精准</option>
                <option value="recall">召回优先</option>
              </select>
            </label>
            <label>
              <span>证据策略</span>
              <select v-model="workbench.retrievalStrategy.value" name="retrieval-strategy">
                <option value="auto">自动关系识别</option>
                <option value="hybrid">混合检索</option>
                <option value="hybrid_graph">混合检索 + 图谱</option>
              </select>
            </label>
            <label>
              <span>返回数量 <strong>{{ workbench.topK.value }}</strong></span>
              <input v-model.number="workbench.topK.value" name="top-k" type="range" min="1" max="12" />
            </label>
            <label>
              <span>候选池</span>
              <input v-model.number="workbench.candidateK.value" name="candidate-k" type="number" min="1" max="80" />
            </label>
            <label>
              <span>向量权重 <strong>{{ workbench.vectorWeight.value.toFixed(2) }}</strong></span>
              <input v-model.number="workbench.vectorBalance.value" name="vector-weight" type="range" min="0" max="1" step="0.01" />
            </label>
            <label>
              <span>MMR λ <strong>{{ workbench.mmrLambda.value.toFixed(2) }}</strong></span>
              <input v-model.number="workbench.mmrLambda.value" name="mmr-lambda" type="range" min="0" max="1" step="0.01" />
            </label>
            <label>
              <span>最低分</span>
              <input v-model.number="workbench.minScore.value" name="min-score" type="number" min="0" max="1" step="0.01" />
            </label>
            <label class="checkbox-field">
              <input v-model="workbench.queryRewrite.value" name="query-rewrite" type="checkbox" />
              <span>查询改写</span>
            </label>
            <label>
              <span>图谱权重 <strong>{{ workbench.graphWeight.value.toFixed(2) }}</strong></span>
              <input v-model.number="workbench.graphWeight.value" name="graph-weight" type="range" min="0" max="1" step="0.05" />
            </label>
            <label>
              <span>图谱跳数</span>
              <input v-model.number="workbench.graphMaxHops.value" name="graph-hops" type="number" min="1" max="4" />
            </label>
            <label>
              <span>父级上下文</span>
              <input v-model.number="workbench.parentWindow.value" name="parent-window" type="number" min="0" max="3" />
            </label>
          </div>
          <fieldset class="modality-filter">
            <legend>检索元素</legend>
            <button
              v-for="item in modalities"
              :key="item.id"
              type="button"
              :aria-pressed="workbench.modalityFilters.value.includes(item.id)"
              @click="toggleModality(item.id)"
            >{{ item.label }}</button>
          </fieldset>
          <p v-if="!workbench.expertParametersValid.value" class="parameter-error" role="status">
            候选池需为 1–80 的整数，最低分需在 0–1 之间。
          </p>
          <div class="expert-run-actions">
            <button
              type="button"
              class="button secondary-button"
              :disabled="workbench.comparing.value || workbench.loading.value || !workbench.question.value.trim() || !workbench.expertParametersValid.value"
              @click="workbench.handleCompare"
            >
              {{ workbench.comparing.value ? '对比中…' : '对比检索策略' }}
            </button>
          </div>
        </div>
      </details>
    </section>

    <div v-if="workbench.error.value" class="error-banner" role="alert">
      <div>
        <strong>请求没有完成</strong>
        <p>{{ workbench.error.value }}</p>
        <small v-if="workbench.errorCode.value">错误代码：{{ workbench.errorCode.value }}</small>
        <small v-if="workbench.errorRequestId.value">请求 ID：{{ workbench.errorRequestId.value }}</small>
      </div>
      <div class="banner-actions">
        <button type="button" class="button secondary-button" @click="workbench.retryLast">重试</button>
        <button type="button" class="button text-button" @click="workbench.clearError">关闭</button>
      </div>
    </div>

    <div v-if="workbench.loading.value" class="query-loading" aria-live="polite">
      <span class="phase-indicator" aria-hidden="true"><i></i><i></i><i></i></span>
      <span v-if="workbench.streamPhase.value === 'enriching'">正在理解图片与查询上下文…</span>
      <span v-else-if="workbench.streamPhase.value === 'retrieving'">正在检索并筛选证据…</span>
      <span v-else-if="workbench.streamPhase.value === 'streaming'">正在生成回答…</span>
      <span v-else-if="workbench.streamPhase.value === 'auditing'">正在核验引用与覆盖率…</span>
      <span v-else>正在处理你的问题…</span>
    </div>

    <form class="question-composer" aria-label="知识库问答" @submit.prevent="workbench.handleRun">
      <div class="composer-context" aria-label="当前检索上下文">
        <span class="live-dot" aria-hidden="true"></span>
        <span>{{ workbench.scopeLabel.value }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ workbench.workMode.value === 'answer' ? '回答并引用' : '仅检索' }}</span>
      </div>

      <div v-if="workbench.queryAttachments.value.length" class="attachment-list" aria-live="polite">
        <article v-for="asset in workbench.queryAttachments.value" :key="asset.id">
          <img :src="asset.preview_url" :alt="`待查询图片：${asset.filename}`" />
          <div><strong>{{ asset.filename }}</strong><span>{{ asset.width }}×{{ asset.height }}</span></div>
          <button type="button" class="button icon-button danger-button" :aria-label="`移除 ${asset.filename}`" @click="workbench.removeQueryAttachment(asset.id)">×</button>
        </article>
        <label class="attachment-detail">
          <span>视觉细节</span>
          <select v-model="workbench.queryAttachmentDetail.value">
            <option value="auto">自动</option>
            <option value="low">低</option>
            <option value="high">高</option>
            <option value="original">原始</option>
          </select>
        </label>
      </div>

      <label class="question-field">
        <span class="sr-only">问题</span>
        <textarea
          ref="questionInput"
          v-model="workbench.question.value"
          name="question"
          maxlength="4000"
          rows="1"
          placeholder="询问你的资料，系统会给出带引用的回答"
          @input="resizeQuestion"
          @keydown.meta.enter.prevent="workbench.handleRun"
          @keydown.ctrl.enter.prevent="workbench.handleRun"
        ></textarea>
      </label>

      <div class="composer-toolbar">
        <div class="composer-tools">
          <label
            class="composer-icon-button"
            :class="{ disabled: workbench.queryAttachmentUploading.value || workbench.queryAttachments.value.length >= 4 }"
            title="添加图片"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
            <span class="sr-only">{{ workbench.queryAttachmentUploading.value ? '正在处理图片' : '添加图片' }}</span>
            <input
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp,image/gif"
              :disabled="workbench.queryAttachmentUploading.value || workbench.queryAttachments.value.length >= 4"
              data-testid="query-image-input"
              @change="onQueryImages"
            />
          </label>
          <div class="mode-switch small" role="group" aria-label="问答方式">
            <button
              type="button"
              :aria-pressed="workbench.workMode.value === 'answer'"
              @click="workbench.workMode.value = 'answer'"
            >回答</button>
            <button
              type="button"
              :aria-pressed="workbench.workMode.value === 'search'"
              :disabled="Boolean(workbench.queryAttachments.value.length)"
              @click="workbench.workMode.value = 'search'"
            >检索</button>
          </div>
          <span class="keyboard-hint">⌘ K 聚焦 · ⌘ 回车发送</span>
        </div>
        <div class="composer-submit">
          <small>{{ workbench.question.value.length }}/4000</small>
          <button
            v-if="workbench.loading.value"
            type="button"
            class="stop-button"
            aria-label="停止生成"
            @click="workbench.cancelRun"
          ><span aria-hidden="true"></span></button>
          <button
            v-else
            type="button"
            class="send-button"
            data-testid="run-query"
            :aria-label="workbench.workMode.value === 'answer' ? '发送问题并生成回答' : '开始检索证据'"
            :disabled="workbench.booting.value || workbench.loading.value || !workbench.question.value.trim() || !workbench.expertParametersValid.value || workbench.queryAttachmentUploading.value"
            @click="workbench.handleRun"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/></svg>
          </button>
        </div>
      </div>
      <p v-if="workbench.queryAttachmentError.value" class="parameter-error" role="status">{{ workbench.queryAttachmentError.value }}</p>
    </form>

    <div v-if="!workbench.answer.value && !workbench.question.value" class="preset-row" aria-label="示例问题">
      <button
        v-for="item in presets"
        :key="item"
        type="button"
        class="suggestion-chip"
        @click="workbench.question.value = item"
      >
        {{ item }}
      </button>
    </div>

    <details
      v-if="workbench.appMode.value === 'expert' && workbench.workMode.value === 'answer'"
      class="usage-evidence"
    >
      <summary>1.0 使用证据记录</summary>
      <label class="usage-attestation">
        <input v-model="workbench.realUsageConsent.value" type="checkbox" />
        <span>
          这是我本人此刻提出的真实问题
          <small>仅明确确认后计入验收 · {{ workbench.realUsageSummary.value?.human_originated_questions ?? 0 }}/100</small>
        </span>
      </label>
    </details>

    <section v-if="workbench.compareResult.value" class="comparison" aria-labelledby="comparison-title">
      <header class="subsection-heading">
        <h3 id="comparison-title">检索策略对比</h3>
        <span>最佳：{{ localizedCompareProfile(workbench.compareResult.value.best_profile) }}</span>
      </header>
      <div class="comparison-grid">
        <article
          v-for="profile in workbench.compareResult.value.profiles"
          :key="profile.id"
          :class="{ best: profile.id === workbench.compareResult.value.best_profile }"
        >
          <strong>{{ localizedCompareProfile(profile.id, profile.label) }}</strong>
          <span>{{ profile.summary.returned }} 条 · 最高分 {{ profile.summary.top_score }}</span>
          <small>{{ profile.summary.top_source }}</small>
        </article>
      </div>
    </section>
  </section>
</template>
