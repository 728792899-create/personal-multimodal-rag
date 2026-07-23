<script setup lang="ts">
import { nextTick, watch } from 'vue'

import { useWorkbenchContext } from '../composables/workbenchContext'
import RetrievalTrace from './RetrievalTrace.vue'
import GraphExplorer from './GraphExplorer.vue'

const workbench = useWorkbenchContext()

const tabs = [
  { id: 'trace', label: 'Trace' },
  { id: 'graph', label: '图谱' },
  { id: 'citation', label: '引用' },
  { id: 'document', label: '文档' },
  { id: 'quality', label: '质量' },
  { id: 'eval', label: '评测' },
] as const

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function elementDomId(id: string) {
  return `element-${id.replace(/[^A-Za-z0-9_-]/g, '-')}`
}

watch(() => workbench.focusedElementId.value, async (id) => {
  if (!id) return
  await nextTick()
  document.getElementById(elementDomId(id))?.focus()
})
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
        <p>完成一次问答后，这里会解释查询增强、混合召回、Graph、父级上下文、排序、拒答与引用审计。</p>
      </div>
    </section>

    <section
      v-else-if="workbench.inspectorTab.value === 'graph'"
      id="panel-graph"
      role="tabpanel"
      aria-labelledby="tab-graph"
      class="inspector-section"
    >
      <div v-if="workbench.graphLoading.value" class="loading-block" aria-live="polite"><span class="spinner" aria-hidden="true"></span>正在加载证据图谱…</div>
      <div v-else-if="workbench.graphError.value" class="inline-notice warning" role="alert">
        <strong>图谱未加载</strong><span>{{ workbench.graphError.value }}</span>
        <button type="button" class="button text-button" @click="workbench.refreshGraph">重试</button>
      </div>
      <GraphExplorer v-else-if="workbench.knowledgeGraph.value" :graph="workbench.knowledgeGraph.value" />
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
        <button
          v-if="workbench.selectedCitation.value.element_ids?.length"
          type="button"
          class="button secondary-button full-width"
          @click="workbench.openCitationElement"
        >定位到精确文档元素</button>
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
        <details class="document-source" open>
          <summary>查看结构化元素</summary>
          <div v-if="workbench.documentElements.value.length" class="element-stack">
            <article
              v-for="element in workbench.documentElements.value"
              :id="elementDomId(element.id)"
              :key="element.id"
              :class="['document-element', `element-${element.type}`, { focused: element.id === workbench.focusedElementId.value }]"
              :tabindex="element.id === workbench.focusedElementId.value ? 0 : -1"
            >
              <header><span class="status-badge neutral">{{ element.type }}</span><small>顺序 {{ element.order + 1 }}{{ element.page_number ? ` · 第 ${element.page_number} 页` : '' }}</small></header>
              <img v-if="element.type === 'image' && element.asset_id" :src="`/api/assets/${element.asset_id}`" :alt="element.caption || element.text || '文档图像元素'" />
              <div v-else-if="element.type === 'table' && element.table.length" class="element-table-wrap" tabindex="0">
                <table><tbody><tr v-for="(row, rowIndex) in element.table" :key="rowIndex"><component :is="rowIndex === 0 ? 'th' : 'td'" v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</component></tr></tbody></table>
              </div>
              <pre v-else-if="element.type === 'equation'" class="equation-block">{{ element.latex || element.text }}</pre>
              <pre v-else-if="element.type === 'code'" class="code-block"><code>{{ element.text }}</code></pre>
              <p v-else class="long-copy">{{ element.text || element.caption || '无可显示内容' }}</p>
              <footer v-if="element.confidence !== null"><small>解析置信度 {{ percent(element.confidence) }}</small></footer>
            </article>
          </div>
          <p v-else class="muted-copy">当前文档尚无元素 IR，可重建索引生成。</p>
        </details>
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
          <div><dt>索引队列</dt><dd>{{ workbench.metrics.value.ingestion?.queue_depth ?? 0 }}</dd></div>
          <div><dt>索引失败</dt><dd>{{ workbench.metrics.value.ingestion?.failed_count ?? 0 }}</dd></div>
          <div><dt>首 Token</dt><dd>{{ workbench.metrics.value.answering.avg_first_token_ms ? `${workbench.metrics.value.answering.avg_first_token_ms} ms` : '—' }}</dd></div>
          <div><dt>索引不兼容</dt><dd>{{ workbench.metrics.value.ingestion?.index_version_mismatch_count ?? 0 }}</dd></div>
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
        <section v-if="workbench.selectedDocument.value?.document.quality?.multimodal" class="inspector-subsection">
          <h3>多模态解析质量</h3>
          <dl class="definition-grid">
            <div><dt>OCR</dt><dd>{{ percent(workbench.selectedDocument.value.document.quality.multimodal.ocr_confidence ?? 0) }}</dd></div>
            <div><dt>Caption 对齐</dt><dd>{{ percent(workbench.selectedDocument.value.document.quality.multimodal.caption_alignment) }}</dd></div>
            <div><dt>表格结构</dt><dd>{{ percent(workbench.selectedDocument.value.document.quality.multimodal.table_structure_accuracy) }}</dd></div>
            <div><dt>公式提取</dt><dd>{{ percent(workbench.selectedDocument.value.document.quality.multimodal.formula_extraction_accuracy) }}</dd></div>
            <div><dt>Graph 证据</dt><dd>{{ percent(workbench.selectedDocument.value.document.quality.multimodal.graph_evidence_coverage) }}</dd></div>
            <div><dt>孤立资产</dt><dd>{{ workbench.selectedDocument.value.document.quality.multimodal.orphan_asset_count }}</dd></div>
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
      <section class="eval-review-summary" aria-live="polite">
        <strong>1.0 人工复核：{{ workbench.evalReviewSummary.value?.human_reviewed || 0 }}/200</strong>
        <span>剩余 {{ workbench.evalReviewSummary.value?.remaining_for_1_0 ?? 200 }} 条；只有逐条确认并留存 reviewer ID 的 case 才计数。</span>
        <label>
          <span>复核人 ID</span>
          <input v-model="workbench.evalReviewerId.value" type="text" autocomplete="off" placeholder="使用团队内稳定的非敏感 ID" />
        </label>
      </section>
      <div v-if="workbench.evalDrafts.value.length" class="eval-list">
        <article v-for="item in workbench.evalDrafts.value.slice(0, 200)" :key="`${item.id}-${item.question}`">
          <span class="status-badge neutral">{{ item.failure_type || item.status }}</span>
          <strong>{{ item.question }}</strong>
          <template v-if="item.status !== 'reviewed'">
            <label>
              <span>期望答案</span>
              <textarea v-model="item.expected_answer" rows="3" placeholder="可回答问题必须填写答案或关键词"></textarea>
            </label>
            <label>
              <span>期望关键词（逗号分隔）</span>
              <input
                :value="(item.expected_keywords || []).join(', ')"
                type="text"
                @input="item.expected_keywords = (($event.target as HTMLInputElement).value || '').split(/[,，]/).map((value) => value.trim()).filter(Boolean)"
              />
            </label>
            <label class="checkbox-row">
              <input v-model="item.answerable" type="checkbox" />
              <span>资料中存在可回答证据</span>
            </label>
            <label>
              <span>复核备注</span>
              <input v-model="item.note" type="text" placeholder="记录证据或争议点" />
            </label>
            <button
              type="button"
              class="button secondary-button"
              :disabled="!workbench.evalReviewerId.value.trim() || workbench.evalReviewingId.value === item.id || (item.answerable !== false && !item.expected_answer?.trim() && !(item.expected_keywords || []).length)"
              @click="workbench.handleReviewEvalCase(item)"
            >{{ workbench.evalReviewingId.value === item.id ? '保存中…' : '确认人工复核' }}</button>
          </template>
          <span v-else class="success-copy">由 {{ item.reviewer_id }} 于 {{ item.reviewed_at }} 复核</span>
        </article>
      </div>
      <p v-if="workbench.evalReviewMessage.value" class="success-copy" aria-live="polite">{{ workbench.evalReviewMessage.value }}</p>
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
