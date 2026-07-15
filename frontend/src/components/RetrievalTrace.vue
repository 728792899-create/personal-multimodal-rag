<script setup lang="ts">
import { computed } from 'vue'

import type { RetrievalTrace } from '../api'


const props = defineProps<{ trace: RetrievalTrace }>()

const reasonLabels: Record<string, string> = {
  no_evidence: '没有证据',
  below_threshold: '低于阈值',
  weak_grounding: '证据关联不足',
  evidence_accepted: '证据通过',
}

const stages = computed(() => {
  const pipeline = props.trace.pipeline || {}
  const decision = pipeline.decision
  return [
    {
      id: 'query-enrichment',
      number: '01',
      title: '查询增强',
      value: props.trace.query_attachments?.length ? `${props.trace.query_attachments.length} 张图片` : '纯文本',
      detail: props.trace.query_attachments?.length ? 'OCR / 视觉描述已纳入检索查询' : '无附件，保持原始查询',
      status: props.trace.query_attachments?.length ? 'success' : 'skipped',
    },
    {
      id: 'bm25',
      number: '02',
      title: 'BM25',
      value: `${pipeline.bm25?.candidates ?? props.trace.bm25_candidates ?? 0} 个候选`,
      detail: `词项召回 · 权重 ${(pipeline.bm25?.weight ?? props.trace.bm25_weight).toFixed(2)}`,
      status: pipeline.bm25?.status || 'unknown',
    },
    {
      id: 'vector',
      number: '03',
      title: '向量召回',
      value: `${pipeline.vector?.candidates ?? props.trace.vector_candidates ?? 0} 个候选`,
      detail: `${props.trace.embedding_provider} · 权重 ${(pipeline.vector?.weight ?? props.trace.vector_weight).toFixed(2)}`,
      status: pipeline.vector?.status || props.trace.vector_status || 'unknown',
    },
    {
      id: 'fusion',
      number: '04',
      title: '融合去重',
      value: `${pipeline.fusion?.deduped ?? props.trace.deduped_candidates ?? 0} 个唯一片段`,
      detail: `来自 ${pipeline.fusion?.candidates ?? props.trace.raw_candidates ?? 0} 个原始候选`,
      status: 'success',
    },
    {
      id: 'graph',
      number: '05',
      title: 'Graph 导航',
      value: pipeline.graph?.status === 'success' ? `${pipeline.graph.paths?.length || 0} 条路径` : '未启用',
      detail: pipeline.graph?.status === 'success'
        ? `${pipeline.graph.seed_count || 0} 个 seed · ${pipeline.graph.evidence_element_ids?.length || 0} 个证据元素`
        : (pipeline.graph?.reason || '当前查询不需要关系导航'),
      status: pipeline.graph?.status || 'skipped',
    },
    {
      id: 'parent',
      number: '06',
      title: '父级上下文',
      value: `窗口 ${props.trace.parent_window ?? 1}`,
      detail: '先定位精确元素，再补充相邻证据',
      status: 'success',
    },
    {
      id: 'mmr',
      number: '07',
      title: 'MMR',
      value: `${pipeline.mmr?.selected ?? props.trace.mmr_selected ?? 0} 个保留`,
      detail: `相关性 / 多样性 λ ${(pipeline.mmr?.lambda ?? props.trace.mmr_lambda).toFixed(2)}`,
      status: 'success',
    },
    {
      id: 'rerank',
      number: '08',
      title: 'Rerank',
      value: `${pipeline.rerank?.returned ?? props.trace.returned ?? 0} 个证据`,
      detail: pipeline.rerank?.provider || props.trace.reranker || 'off',
      status: pipeline.rerank?.status || props.trace.rerank_status || 'unknown',
    },
    {
      id: 'decision',
      number: '09',
      title: '回答决策',
      value: decision?.status === 'refused' || props.trace.refusal_reason ? '拒绝回答' : '允许回答',
      detail: reasonLabels[decision?.reason || props.trace.refusal_reason || 'evidence_accepted'] || decision?.reason || '证据通过',
      status: decision?.status === 'refused' || props.trace.refusal_reason ? 'refused' : 'success',
    },
    {
      id: 'citation',
      number: '10',
      title: '引用覆盖率',
      value: `${Math.round((pipeline.citation_audit?.coverage ?? 0) * 100)}%`,
      detail: `证据贴合度 ${Math.round((pipeline.citation_audit?.grounding ?? 0) * 100)}%`,
      status: pipeline.citation_audit?.status || 'pending',
    },
  ]
})
</script>

<template>
  <section class="trace-visual" aria-labelledby="trace-title">
    <header class="section-heading compact">
      <div>
        <p class="kicker">Retrieval trace</p>
        <h2 id="trace-title">检索阶段</h2>
      </div>
      <span class="status-badge neutral">{{ trace.search_profile }}</span>
    </header>

    <ol class="trace-stages" aria-label="从召回到引用审计的检索流程">
      <li
        v-for="stage in stages"
        :key="stage.id"
        data-trace-stage
        :data-stage="stage.id"
        :class="['trace-stage', `is-${stage.status}`]"
      >
        <span class="stage-index" aria-hidden="true">{{ stage.number }}</span>
        <div>
          <h3>{{ stage.title }}</h3>
          <strong>{{ stage.value }}</strong>
          <p>{{ stage.detail }}</p>
        </div>
      </li>
    </ol>

    <section v-if="trace.pipeline?.graph?.paths?.length" class="graph-path-summary" aria-labelledby="trace-path-title">
      <h3 id="trace-path-title">Provenance-backed 路径</h3>
      <ol>
        <li v-for="(path, index) in trace.pipeline.graph.paths.slice(0, 4)" :key="`${path.edge_ids?.join('-')}-${index}`">
          <strong>{{ path.labels.join(' → ') }}</strong>
          <span>{{ path.relations.join(' / ') }} · {{ path.evidence_element_ids.length }} 个证据元素</span>
        </li>
      </ol>
    </section>

    <details class="trace-details">
      <summary>查看查询与性能细节</summary>
      <dl class="definition-grid">
        <div>
          <dt>查询改写</dt>
          <dd>{{ trace.rewrite_status || '—' }}</dd>
        </div>
        <div>
          <dt>候选池</dt>
          <dd>{{ trace.candidate_k }}</dd>
        </div>
        <div>
          <dt>最低分</dt>
          <dd>{{ trace.min_score ?? trace.no_answer_threshold }}</dd>
        </div>
        <div>
          <dt>总耗时</dt>
          <dd>{{ trace.performance?.total_ms ?? '—' }} ms</dd>
        </div>
      </dl>
      <ul class="plain-list query-variants">
        <li v-for="item in trace.rewritten_queries" :key="item">{{ item }}</li>
      </ul>
    </details>

    <div v-if="trace.fallbacks?.length" class="inline-notice warning" role="note">
      <strong>链路已降级</strong>
      <span v-for="item in trace.fallbacks" :key="`${item.stage}-${item.action}`">
        {{ item.stage }}：{{ item.action }}
      </span>
    </div>
  </section>
</template>
