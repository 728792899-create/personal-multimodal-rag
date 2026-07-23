<script setup lang="ts">
import { computed } from 'vue'

import { exportHistoryUrl } from '../api'
import { useWorkbenchContext } from '../composables/workbenchContext'

const workbench = useWorkbenchContext()

const resultLabel = computed(() => {
  if (workbench.streamAuditPending.value) return '生成中 · 待审计'
  if (workbench.isRefusal.value) return '已安全拒答'
  if (workbench.workMode.value === 'search') return '检索完成'
  return '回答已生成'
})

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`
}
</script>

<template>
  <section v-if="workbench.answer.value" class="surface answer-experience" aria-labelledby="answer-title">
    <header class="answer-header">
      <div>
        <p class="kicker">Grounded result</p>
        <h2 id="answer-title">{{ workbench.workMode.value === 'search' ? '检索证据' : '证据回答' }}</h2>
      </div>
      <div
        :class="['result-status', { refused: workbench.isRefusal.value, pending: workbench.streamAuditPending.value }]"
        role="status"
        aria-live="polite"
      >
        <span aria-hidden="true">{{ workbench.isRefusal.value ? '!' : '✓' }}</span>
        {{ resultLabel }}
      </div>
    </header>

    <section v-if="workbench.streamAuditPending.value" class="trust-summary audit-pending" role="status" aria-live="polite">
      <div>
        <span class="status-badge neutral">引用审计中</span>
        <strong>当前文本尚未形成最终可信结论</strong>
        <p>完整响应到达后，系统才会展示引用准确性、覆盖率和可信等级。</p>
      </div>
    </section>
    <section v-else-if="workbench.trust.value" :class="['trust-summary', `trust-${workbench.trust.value.level}`]">
      <div>
        <span class="status-badge">{{ workbench.trust.value.label }}</span>
        <strong>置信度 {{ percent(workbench.answer.value.confidence || 0) }}</strong>
        <p>{{ workbench.trust.value.reason }}</p>
      </div>
      <dl>
        <div><dt>证据</dt><dd>{{ workbench.trust.value.evidence_count }}</dd></div>
        <div><dt>来源</dt><dd>{{ workbench.trust.value.source_count }}</dd></div>
        <div><dt>覆盖</dt><dd>{{ percent(workbench.citationAudit.value?.coverage) }}</dd></div>
      </dl>
    </section>

    <article v-if="workbench.answer.value.answer" class="answer-copy">
      <p>{{ workbench.answer.value.answer }}</p>
    </article>
    <div v-else class="empty-state compact-empty">
      <strong>当前是只检索模式</strong>
      <p>系统没有生成结论，请逐条核验证据。</p>
    </div>

    <section v-if="workbench.diagnostics.value.length" class="diagnostic-stack" aria-labelledby="diagnostics-title">
      <h3 id="diagnostics-title">可执行建议</h3>
      <article v-for="item in workbench.diagnostics.value" :key="`${item.level}-${item.title}`" :class="['diagnostic-item', item.level]">
        <div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.message }}</p>
        </div>
        <div v-if="item.actions?.length" class="inline-actions">
          <button
            v-for="action in item.actions"
            :key="action.id"
            type="button"
            class="button secondary-button"
            @click="workbench.handleDiagnosticAction(action)"
          >{{ action.label }}</button>
        </div>
      </article>
    </section>

    <section class="evidence-section" aria-labelledby="evidence-title">
      <header class="subsection-heading">
        <div>
          <h3 id="evidence-title">引用证据</h3>
          <span>{{ workbench.answer.value.citations.length }} 条</span>
        </div>
        <small>点击证据查看相邻上下文</small>
      </header>
      <ol v-if="workbench.answer.value.citations.length" class="citation-list">
        <li v-for="(item, index) in workbench.answer.value.citations" :key="item.id">
          <button
            type="button"
            :data-testid="`citation-${index + 1}`"
            :aria-current="workbench.selectedCitation.value?.id === item.id ? 'true' : undefined"
            @click="workbench.selectCitation(item)"
          >
            <span class="citation-number">{{ index + 1 }}</span>
            <span class="citation-main">
              <strong>{{ item.filename }} · 片段 {{ item.index + 1 }}</strong>
              <span>{{ item.snippet || item.text }}</span>
              <small>
                rerank {{ item.rerank_score.toFixed(3) }} · BM25 {{ item.bm25_score.toFixed(3) }} · vector {{ item.vector_score.toFixed(3) }}
              </small>
            </span>
            <span aria-hidden="true">→</span>
          </button>
        </li>
      </ol>
      <div v-else class="empty-state compact-empty">
        <strong>没有可引用证据</strong>
        <p>拒答保护已阻止无证据内容进入答案。</p>
      </div>
    </section>

    <section v-if="workbench.answer.value.answer && !workbench.streamAuditPending.value" class="answer-actions" aria-labelledby="answer-actions-title">
      <h3 id="answer-actions-title">复用与反馈</h3>
      <div class="inline-actions wrap-actions">
        <button type="button" class="button secondary-button" :disabled="workbench.rewriting.value" @click="workbench.handleRewrite('highlights')">改写为要点</button>
        <button type="button" class="button secondary-button" :disabled="workbench.rewriting.value" @click="workbench.handleRewrite('study')">改写为笔记</button>
        <button type="button" class="button secondary-button" @click="workbench.handleSaveCard">保存知识卡片</button>
        <a
          v-if="workbench.answer.value.history_id"
          class="button secondary-button"
          :href="exportHistoryUrl(workbench.answer.value.history_id)"
          download
        >导出 Markdown</a>
      </div>
      <div v-if="workbench.rewriteResult.value" class="rewrite-result">
        <strong>{{ workbench.rewriteResult.value.label }}</strong>
        <p>{{ workbench.rewriteResult.value.rewritten }}</p>
      </div>
      <p v-if="workbench.cardMessage.value" class="success-copy">{{ workbench.cardMessage.value }}</p>

      <label class="feedback-field">
        <span>补充说明（可选）</span>
        <input v-model="workbench.feedbackText.value" type="text" placeholder="哪里准确，或哪里需要修正？" />
      </label>
      <div class="inline-actions wrap-actions">
        <button type="button" class="button secondary-button" :disabled="workbench.feedbackSubmitting.value" @click="workbench.handleFeedback('up')">回答有效</button>
        <button type="button" class="button danger-outline-button" data-testid="feedback-down" :disabled="workbench.feedbackSubmitting.value" @click="workbench.handleFeedback('down')">需要改进并生成评测草稿</button>
        <span v-if="workbench.feedbackMessage.value" class="success-copy" aria-live="polite">{{ workbench.feedbackMessage.value }}</span>
      </div>
    </section>
  </section>

  <section v-else-if="!workbench.loading.value" class="surface empty-answer" aria-labelledby="empty-answer-title">
    <div class="empty-illustration" aria-hidden="true">↳</div>
    <h2 id="empty-answer-title">从一个可验证的问题开始</h2>
    <p>答案会与引用、检索过程和质量审计放在同一上下文中。</p>
    <ul>
      <li>有证据时返回可追溯引用</li>
      <li>证据不足时明确拒答</li>
      <li>负反馈可直接沉淀为评测草稿</li>
    </ul>
  </section>
</template>
