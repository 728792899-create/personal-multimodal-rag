<script setup lang="ts">
import { useWorkbenchContext } from '../composables/workbenchContext'
import RetrievalTrace from './RetrievalTrace.vue'

const workbench = useWorkbenchContext()

const tabs = [
  { id: 'trace', label: 'Trace' },
  { id: 'citation', label: '引用' },
  { id: 'document', label: '文档' },
  { id: 'quality', label: '质量' },
  { id: 'eval', label: '评测' },
] as const

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`
}
</script>

<template>
  <aside class="surface inspector-panel" aria-labelledby="inspector-title">
    <header class="section-heading">
      <div>
        <p class="kicker">Inspect & improve</p>
        <h2 id="inspector-title">验证与质量</h2>
      </div>
      <span class="status-badge neutral">{{ workbench.appMode.value === 'expert' ? '专家视图' : '摘要视图' }}</span>
    </header>

    <div class="inspector-tabs" role="tablist" aria-label="验证面板">
      <button
        v-for="tab in tabs"
        :id="`tab-${tab.id}`"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="workbench.inspectorTab.value === tab.id"
        :aria-controls="`panel-${tab.id}`"
        @click="workbench.inspectorTab.value = tab.id"
      >{{ tab.label }}</button>
    </div>

    <section
      v-if="workbench.inspectorTab.value === 'trace'"
      id="panel-trace"
      role="tabpanel"
      aria-labelledby="tab-trace"
    >
      <RetrievalTrace v-if="workbench.answer.value" :trace="workbench.answer.value.retrieval_trace" />
      <div v-else class="empty-state compact-empty">
        <strong>尚无检索过程</strong>
        <p>完成一次问答后，这里会逐步解释 BM25、向量、MMR、Rerank 和拒答决策。</p>
      </div>
    </section>

    <section
      v-else-if="workbench.inspectorTab.value === 'citation'"
      id="panel-citation"
      role="tabpanel"
      aria-labelledby="tab-citation"
      class="inspector-section"
    >
      <template v-if="workbench.selectedCitation.value">
        <header class="subsection-heading stacked-heading">
          <div>
            <h3>{{ workbench.selectedCitation.value.filename }}</h3>
            <span>片段 {{ workbench.selectedCitation.value.index + 1 }}</span>
          </div>
          <small>rerank {{ workbench.selectedCitation.value.rerank_score.toFixed(3) }}</small>
        </header>
        <p class="long-copy">{{ workbench.selectedCitation.value.text }}</p>
        <div class="score-breakdown">
          <span>BM25 {{ workbench.selectedCitation.value.bm25_score.toFixed(3) }}</span>
          <span>Vector {{ workbench.selectedCitation.value.vector_score.toFixed(3) }}</span>
          <span>Base {{ workbench.selectedCitation.value.score.toFixed(3) }}</span>
        </div>
        <div v-if="workbench.loadingContext.value" class="loading-block" aria-live="polite">
          <span class="spinner" aria-hidden="true"></span>正在加载相邻上下文…
        </div>
        <div v-else-if="workbench.citationContext.value" class="context-stack">
          <h3>相邻上下文</h3>
          <article
            v-for="item in workbench.citationContext.value.context"
            :key="item.id"
            :class="{ current: item.is_current }"
          >
            <strong>片段 {{ item.index + 1 }}{{ item.is_current ? ' · 当前引用' : '' }}</strong>
            <p>{{ item.text }}</p>
          </article>
        </div>
      </template>
      <div v-else class="empty-state compact-empty">
        <strong>尚未选择引用</strong>
        <p>在回答区域选择一条证据查看完整上下文。</p>
      </div>
    </section>

    <section
      v-else-if="workbench.inspectorTab.value === 'document'"
      id="panel-document"
      role="tabpanel"
      aria-labelledby="tab-document"
      class="inspector-section"
    >
      <div v-if="workbench.loadingDocument.value" class="loading-block" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>文档详情加载中…
      </div>
      <template v-else-if="workbench.selectedDocument.value">
        <header class="subsection-heading stacked-heading">
          <div>
            <h3>{{ workbench.selectedDocument.value.document.filename }}</h3>
            <span>{{ workbench.selectedDocument.value.document.source_type }}</span>
          </div>
          <span class="status-badge">Q {{ workbench.selectedDocument.value.document.quality?.score ?? '—' }}</span>
        </header>
        <dl class="definition-grid">
          <div><dt>页数</dt><dd>{{ workbench.selectedDocument.value.document.page_count }}</dd></div>
          <div><dt>片段</dt><dd>{{ workbench.selectedDocument.value.document.chunk_count }}</dd></div>
          <div><dt>字符</dt><dd>{{ workbench.selectedDocument.value.document.char_count }}</dd></div>
          <div><dt>Parser</dt><dd>{{ workbench.selectedDocument.value.document.metadata.parser || '—' }}</dd></div>
        </dl>
        <section v-if="workbench.selectedDocument.value.document.summary" class="inspector-subsection">
          <h3>自动摘要</h3>
          <p class="long-copy">{{ workbench.selectedDocument.value.document.summary.one_sentence }}</p>
          <div class="tag-row">
            <span v-for="item in workbench.selectedDocument.value.document.summary.key_concepts.slice(0, 8)" :key="item">{{ item }}</span>
          </div>
        </section>
        <details class="document-source">
          <summary>查看原文与切片</summary>
          <p class="long-copy">{{ workbench.selectedDocument.value.document.pages[0]?.text || '没有可显示文本。' }}</p>
          <article v-for="chunk in workbench.selectedDocument.value.chunks.slice(0, 8)" :key="chunk.id">
            <strong>片段 {{ chunk.index + 1 }}</strong>
            <p>{{ chunk.text }}</p>
          </article>
        </details>
      </template>
      <div v-else class="empty-state compact-empty">
        <strong>尚未选择文档</strong>
        <p>从知识库列表打开文档详情。</p>
      </div>
    </section>

    <section
      v-else-if="workbench.inspectorTab.value === 'quality'"
      id="panel-quality"
      role="tabpanel"
      aria-labelledby="tab-quality"
      class="inspector-section"
    >
      <div v-if="workbench.metrics.value" class="quality-dashboard">
        <dl class="metric-grid">
          <div><dt>平均置信度</dt><dd>{{ percent(workbench.metrics.value.answering.avg_confidence) }}</dd></div>
          <div><dt>拒答</dt><dd>{{ workbench.metrics.value.answering.no_answer_count }}</dd></div>
          <div><dt>Fallback</dt><dd>{{ workbench.metrics.value.answering.fallback_count }}</dd></div>
          <div><dt>负反馈</dt><dd>{{ workbench.metrics.value.feedback.negative }}</dd></div>
        </dl>
        <section class="inspector-subsection">
          <h3>知识库健康</h3>
          <p v-if="workbench.overview.value" class="long-copy">
            {{ workbench.overview.value.document_count }} 份文档，平均质量 {{ workbench.avgQualityLabel.value }}，
            {{ workbench.overview.value.quality_distribution.needs_work }} 份需要复核。
          </p>
          <ul class="plain-list">
            <li v-for="item in workbench.overview.value?.suggestions || []" :key="item">{{ item }}</li>
          </ul>
        </section>
        <section class="inspector-subsection">
          <h3>引用审计</h3>
          <dl class="definition-grid">
            <div><dt>覆盖率</dt><dd>{{ percent(workbench.citationAudit.value?.coverage) }}</dd></div>
            <div><dt>贴合度</dt><dd>{{ percent(workbench.citationAudit.value?.grounding) }}</dd></div>
            <div><dt>支持句</dt><dd>{{ workbench.citationAudit.value?.supported_sentence_count ?? 0 }}</dd></div>
            <div><dt>未支持句</dt><dd>{{ workbench.citationAudit.value?.unsupported_sentence_count ?? 0 }}</dd></div>
          </dl>
        </section>
        <section v-if="workbench.operations.value.length" class="inspector-subsection">
          <h3>最近操作</h3>
          <ul class="operation-list">
            <li v-for="item in workbench.operations.value.slice(0, 6)" :key="item.id">
              <span :class="['level-dot', item.level]" aria-hidden="true"></span>
              <div><strong>{{ item.event_type }}</strong><p>{{ item.message }}</p></div>
            </li>
          </ul>
        </section>
      </div>
      <div v-else class="empty-state compact-empty"><strong>指标加载中</strong><p>稍后重试。</p></div>
    </section>

    <section
      v-else
      id="panel-eval"
      role="tabpanel"
      aria-labelledby="tab-eval"
      class="inspector-section"
    >
      <form class="eval-form" @submit.prevent="workbench.handleCreateEvalCase">
        <label>
          <span>评测问题</span>
          <input v-model="workbench.evalQuestion.value" type="text" placeholder="输入固定回归问题" />
        </label>
        <label>
          <span>期望关键词</span>
          <input v-model="workbench.evalKeywords.value" type="text" placeholder="用逗号分隔" />
        </label>
        <div class="inline-actions">
          <button type="submit" class="button secondary-button" :disabled="!workbench.evalQuestion.value.trim()">添加 Case</button>
          <button type="button" class="button primary-button" :disabled="workbench.evalRunning.value" @click="workbench.handleRunEvalDrafts">
            {{ workbench.evalRunning.value ? '评测中…' : '运行草稿' }}
          </button>
        </div>
      </form>
      <div v-if="workbench.evalDrafts.value.length" class="eval-list">
        <article v-for="item in workbench.evalDrafts.value.slice(0, 8)" :key="`${item.id}-${item.question}`">
          <span class="status-badge neutral">{{ item.failure_type || item.status }}</span>
          <strong>{{ item.question }}</strong>
        </article>
      </div>
      <div v-else class="empty-state compact-empty">
        <strong>还没有评测草稿</strong>
        <p>手动添加，或对回答给出负反馈后自动生成。</p>
      </div>
      <div v-if="workbench.evalResults.value.length" class="eval-results">
        <article v-for="item in workbench.evalResults.value" :key="item.question" :class="{ failed: !item.hit }">
          <strong>{{ item.hit ? '通过' : '未通过' }}</strong>
          <span>{{ item.question }}</span>
        </article>
      </div>
    </section>
  </aside>
</template>
