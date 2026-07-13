<script setup lang="ts">
import { useWorkbenchContext } from '../composables/workbenchContext'

const workbench = useWorkbenchContext()

const presets = [
  '这个 RAG 系统的核心工程亮点是什么？',
  '这个系统如何通过引用和拒答机制降低幻觉？',
  '这份资料有没有提到 Kubernetes 部署？',
]
</script>

<template>
  <section class="surface query-workspace" aria-labelledby="query-title">
    <header class="section-heading query-heading">
      <div>
        <p class="kicker">Ask with evidence</p>
        <h2 id="query-title">向知识库提问</h2>
      </div>
      <div class="mode-switch small" role="group" aria-label="问答方式">
        <button
          type="button"
          :aria-pressed="workbench.workMode.value === 'answer'"
          @click="workbench.workMode.value = 'answer'"
        >问答</button>
        <button
          type="button"
          :aria-pressed="workbench.workMode.value === 'search'"
          @click="workbench.workMode.value = 'search'"
        >只检索</button>
      </div>
    </header>

    <label class="question-field">
      <span>问题</span>
      <textarea
        v-model="workbench.question.value"
        name="question"
        maxlength="4000"
        placeholder="描述你要确认的事实、范围或来源…"
        @keydown.meta.enter.prevent="workbench.handleRun"
        @keydown.ctrl.enter.prevent="workbench.handleRun"
      ></textarea>
      <small>⌘/Ctrl + Enter 运行 · {{ workbench.question.value.length }}/4000</small>
    </label>

    <div class="preset-row" aria-label="示例问题">
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

    <section v-if="workbench.appMode.value === 'expert'" class="expert-controls" aria-labelledby="expert-title">
      <header>
        <div>
          <p class="kicker">Expert controls</p>
          <h3 id="expert-title">检索参数</h3>
        </div>
        <button type="button" class="button text-button" @click="workbench.resetRetrievalControls">恢复默认</button>
      </header>
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
          <span>检索 Profile</span>
          <select v-model="workbench.searchProfile.value" name="search-profile">
            <option value="balanced">Balanced</option>
            <option value="precision">Precision</option>
            <option value="recall">Recall</option>
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
          <span>启用 Query Rewrite</span>
        </label>
      </div>
      <p class="control-summary">
        BM25 {{ workbench.bm25Weight.value.toFixed(2) }} / Vector {{ workbench.vectorWeight.value.toFixed(2) }} ·
        {{ workbench.scopeLabel.value }}
      </p>
    </section>

    <div v-else class="default-profile-note">
      <div>
        <strong>平衡检索已启用</strong>
        <span>混合召回、MMR、Rerank 与拒答保护会自动运行。</span>
      </div>
      <button type="button" class="button text-button" @click="workbench.appMode.value = 'expert'">调整参数</button>
    </div>

    <div v-if="workbench.error.value" class="error-banner" role="alert">
      <div>
        <strong>操作未完成</strong>
        <p>{{ workbench.error.value }}</p>
        <small v-if="workbench.errorRequestId.value">请求 ID：{{ workbench.errorRequestId.value }}</small>
      </div>
      <div class="banner-actions">
        <button type="button" class="button secondary-button" @click="workbench.retryLast">重试</button>
        <button type="button" class="button text-button" @click="workbench.clearError">关闭</button>
      </div>
    </div>

    <div class="run-bar">
      <div class="run-context">
        <span>{{ workbench.scopeLabel.value }}</span>
        <span>{{ workbench.workMode.value === 'answer' ? '生成证据回答' : '只返回证据' }}</span>
      </div>
      <div class="run-actions">
        <button
          v-if="workbench.appMode.value === 'expert'"
          type="button"
          class="button secondary-button"
          :disabled="workbench.comparing.value || workbench.loading.value || !workbench.question.value.trim()"
          @click="workbench.handleCompare"
        >
          {{ workbench.comparing.value ? '对比中…' : '策略对比' }}
        </button>
        <button
          v-if="workbench.loading.value"
          type="button"
          class="button danger-outline-button"
          @click="workbench.cancelRun"
        >取消请求</button>
        <button
          v-else
          type="button"
          class="button primary-button run-button"
          data-testid="run-query"
          :disabled="!workbench.question.value.trim()"
          @click="workbench.handleRun"
        >
          {{ workbench.workMode.value === 'answer' ? '检索并回答' : '检索证据' }}
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </div>

    <div v-if="workbench.loading.value" class="query-loading" aria-live="polite">
      <span class="spinner" aria-hidden="true"></span>
      正在召回、去重并审计证据…
    </div>

    <section v-if="workbench.compareResult.value" class="comparison" aria-labelledby="comparison-title">
      <header class="subsection-heading">
        <h3 id="comparison-title">检索策略对比</h3>
        <span>最佳：{{ workbench.compareResult.value.best_profile }}</span>
      </header>
      <div class="comparison-grid">
        <article
          v-for="profile in workbench.compareResult.value.profiles"
          :key="profile.id"
          :class="{ best: profile.id === workbench.compareResult.value.best_profile }"
        >
          <strong>{{ profile.label }}</strong>
          <span>{{ profile.summary.returned }} 条 · top {{ profile.summary.top_score }}</span>
          <small>{{ profile.summary.top_source }}</small>
        </article>
      </div>
    </section>
  </section>
</template>
