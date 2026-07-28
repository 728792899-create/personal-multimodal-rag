<script setup lang="ts">
import { computed } from 'vue'

import { exportHistoryUrl, type ChunkResult } from '../api'
import { useWorkbenchContext } from '../composables/workbenchContext'
import { localizedSystemText } from '../localization'

const workbench = useWorkbenchContext()
const emit = defineEmits<{
  openInspector: []
}>()

const resultLabel = computed(() => {
  if (workbench.streamAuditPending.value) return '生成中 · 待审计'
  if (workbench.workMode.value === 'search') return '检索完成'
  if (!workbench.answerFinalized.value) {
    return workbench.answer.value?.citations.length ? '回答未完成 · 证据已保留' : '回答未完成'
  }
  if (workbench.isRefusal.value) return '已安全拒答'
  if (!workbench.answer.value?.answer) return '检索完成 · 无正文'
  return '回答已生成'
})

const trustPassed = computed(() => (
  ['strong', 'medium'].includes(workbench.trust.value?.level || '')
))

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function openCitation(item: ChunkResult) {
  workbench.selectCitation(item)
  emit('openInspector')
}
</script>

<template>
  <section v-if="workbench.answer.value" class="answer-experience" aria-labelledby="answer-title">
    <header class="answer-header">
      <div class="answer-identity">
        <span class="assistant-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M6 4h9l3 3v13H6z"/><path d="M15 4v4h4M9 12h6M9 16h4"/></svg>
        </span>
        <h2 id="answer-title">{{ workbench.workMode.value === 'search' ? '检索结果' : '回答' }}</h2>
      </div>
      <div
        :class="['result-status', { refused: workbench.isRefusal.value, pending: workbench.streamAuditPending.value }]"
        role="status"
        aria-live="polite"
      >
        <span class="status-signal" aria-hidden="true"></span>
        {{ resultLabel }}
      </div>
    </header>

    <section v-if="workbench.streamAuditPending.value" class="trust-summary audit-pending" role="status" aria-live="polite">
      <span class="status-signal" aria-hidden="true"></span>
      <div><strong>正在核验引用</strong><p>审计完成前，回答不会被标记为可信结论。</p></div>
    </section>
    <section v-else-if="!workbench.answerFinalized.value" class="trust-summary trust-incomplete" role="status" aria-live="polite">
      <div>
        <span class="trust-label">未完成</span>
        <strong>这不是已审计的最终回答</strong>
        <p>中断前生成的片段仅供参考，尚未完成引用审计。</p>
      </div>
    </section>
    <section v-else-if="workbench.trust.value" :class="['trust-summary', `trust-${workbench.trust.value.level}`]">
      <div>
        <span class="trust-label">{{ localizedSystemText(workbench.trust.value.label, '证据状态') }}</span>
        <strong>
          {{
            workbench.workMode.value === 'search'
              ? '请逐条核验来源'
              : workbench.isRefusal.value
                ? '证据不足，系统没有补写结论'
                : trustPassed
                  ? '已通过引用核验'
                  : workbench.trust.value.level === 'weak'
                    ? '引用核验未通过'
                    : '证据关联不足'
          }}
        </strong>
        <p>{{ localizedSystemText(workbench.trust.value.reason, '请查看引用证据后再判断。') }}</p>
      </div>
      <dl>
        <div><dt>{{ workbench.workMode.value === 'search' ? '匹配度' : '可信度' }}</dt><dd>{{ percent(workbench.answer.value.confidence || 0) }}</dd></div>
        <div><dt>{{ workbench.workMode.value === 'search' ? '证据' : '引用' }}</dt><dd>{{ workbench.trust.value.evidence_count }}</dd></div>
        <div v-if="workbench.workMode.value !== 'search'"><dt>覆盖率</dt><dd>{{ percent(workbench.citationAudit.value?.coverage) }}</dd></div>
      </dl>
    </section>

    <article v-if="workbench.answer.value.answer" class="answer-copy">
      <p>{{ workbench.answer.value.answer }}</p>
    </article>
    <div v-else-if="workbench.streamAuditPending.value" class="answer-stream-skeleton" role="status" aria-live="polite">
      <div aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <p>证据已经就绪，正在组织回答。</p>
    </div>
    <div v-else class="empty-state compact-empty">
      <strong>
        {{
          workbench.workMode.value === 'search'
            ? '当前是只检索模式'
            : workbench.error.value && workbench.answer.value.citations.length
              ? '回答生成未完成'
              : '回答链路未返回正文'
        }}
      </strong>
      <p>
        {{
          workbench.workMode.value === 'search'
            ? '系统没有生成结论，请逐条核验证据。'
            : workbench.error.value && workbench.answer.value.citations.length
              ? `检索已经完成，并保留了 ${workbench.answer.value.citations.length} 条证据；请重试回答生成。`
              : '系统保留了可用检索证据，请查看诊断并重试生成。'
        }}
      </p>
    </div>

    <details v-if="workbench.diagnostics.value.length" class="diagnostic-stack">
      <summary>查看诊断建议</summary>
      <div>
        <article v-for="item in workbench.diagnostics.value" :key="`${item.level}-${item.title}`" :class="['diagnostic-item', item.level]">
          <div>
            <strong>{{ localizedSystemText(item.title, '检索诊断') }}</strong>
            <p>{{ localizedSystemText(item.message, '请检查检索设置后重试。') }}</p>
          </div>
          <div v-if="item.actions?.length" class="inline-actions">
            <button
              v-for="action in item.actions"
              :key="action.id"
              type="button"
              class="button secondary-button"
              @click="workbench.handleDiagnosticAction(action)"
            >{{ localizedSystemText(action.label, '执行建议') }}</button>
          </div>
        </article>
      </div>
    </details>

    <section class="evidence-section" aria-labelledby="evidence-title">
      <header class="subsection-heading">
        <div>
          <h3 id="evidence-title">来源 <span>{{ workbench.answer.value.citations.length }}</span></h3>
          <p>点击来源，查看原文和完整检索路径</p>
        </div>
      </header>
      <ol v-if="workbench.answer.value.citations.length" class="citation-list">
        <li v-for="(item, index) in workbench.answer.value.citations" :key="item.id">
          <button
            type="button"
            :data-testid="`citation-${index + 1}`"
            :aria-current="workbench.selectedCitation.value?.id === item.id ? 'true' : undefined"
            @click="openCitation(item)"
          >
            <span class="citation-number">{{ index + 1 }}</span>
            <span class="citation-main">
              <strong>{{ item.filename }}</strong>
              <span>{{ item.snippet || item.text }}</span>
              <small v-if="workbench.appMode.value === 'expert'">
                片段 {{ item.index + 1 }} · 重排序 {{ item.rerank_score.toFixed(3) }} · BM25 {{ item.bm25_score.toFixed(3) }} · 向量 {{ item.vector_score.toFixed(3) }}
              </small>
            </span>
            <span class="citation-open" aria-hidden="true">↗</span>
          </button>
        </li>
      </ol>
      <div v-else class="empty-state compact-empty">
        <strong>没有可引用证据</strong>
        <p>拒答保护已阻止无证据内容进入答案。</p>
      </div>
    </section>

    <section v-if="workbench.answer.value.answer && workbench.answerFinalized.value" class="answer-actions" aria-labelledby="answer-actions-title">
      <h3 id="answer-actions-title" class="sr-only">回答操作与反馈</h3>
      <div class="inline-actions answer-tool-row">
        <button type="button" class="answer-tool" :disabled="workbench.rewriting.value" @click="workbench.handleRewrite('highlights')">整理为要点</button>
        <button type="button" class="answer-tool" :disabled="workbench.rewriting.value" @click="workbench.handleRewrite('study')">转为笔记</button>
        <button type="button" class="answer-tool" @click="workbench.handleSaveCard">保存</button>
        <a
          v-if="workbench.answer.value.history_id"
          class="answer-tool"
          :href="exportHistoryUrl(workbench.answer.value.history_id)"
          download
        >导出</a>
      </div>
      <div v-if="workbench.rewriteResult.value" class="rewrite-result">
        <strong>{{ localizedSystemText(workbench.rewriteResult.value.label, '整理后的回答') }}</strong>
        <p>{{ workbench.rewriteResult.value.rewritten }}</p>
      </div>
      <p v-if="workbench.cardMessage.value" class="success-copy">{{ workbench.cardMessage.value }}</p>

      <details class="feedback-details" open>
        <summary>反馈这次回答</summary>
        <label class="feedback-field">
          <span>补充说明（可选）</span>
          <input v-model="workbench.feedbackText.value" type="text" placeholder="哪里准确，或哪里需要修正？" />
        </label>
        <div class="inline-actions wrap-actions">
          <button type="button" class="button secondary-button" :disabled="workbench.feedbackSubmitting.value" @click="workbench.handleFeedback('up')">回答有效</button>
          <button type="button" class="button danger-outline-button" data-testid="feedback-down" :disabled="workbench.feedbackSubmitting.value" @click="workbench.handleFeedback('down')">需要改进并生成评测草稿</button>
        </div>
      </details>
      <div>
        <span v-if="workbench.feedbackMessage.value" class="success-copy" aria-live="polite">{{ workbench.feedbackMessage.value }}</span>
      </div>
    </section>
  </section>

  <section v-else-if="!workbench.loading.value && workbench.appMode.value === 'user'" class="empty-answer" aria-labelledby="empty-answer-title">
    <div class="empty-product-mark" aria-hidden="true">
      <svg viewBox="0 0 48 48"><path d="M11 8h19l7 7v25H11z"/><path d="M30 8v9h8M17 23h14M17 29h14M17 35h8"/><path d="m29 34 3 3 6-7"/></svg>
    </div>
    <h2 id="empty-answer-title">向你的知识库提问</h2>
    <p>上传文档或图片，获得带原文引用、可继续核验的回答。</p>
    <div class="empty-capabilities" aria-label="问答能力">
      <span>混合检索</span>
      <span>精确引用</span>
      <span>证据不足时拒答</span>
    </div>
  </section>
</template>
