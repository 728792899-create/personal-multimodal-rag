import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RetrievalTrace from './RetrievalTrace.vue'
import { traceFixture } from '../test/fixtures'


describe('RetrievalTrace', () => {
  it('explains every retrieval and grounding stage with counts and decisions', () => {
    const wrapper = mount(RetrievalTrace, { props: { trace: traceFixture } })

    expect(wrapper.text()).toContain('BM25')
    expect(wrapper.text()).toContain('9 个候选')
    expect(wrapper.text()).toContain('向量召回')
    expect(wrapper.text()).toContain('11 个候选')
    expect(wrapper.text()).toContain('融合去重')
    expect(wrapper.text()).toContain('MMR')
    expect(wrapper.text()).toContain('6 个保留')
    expect(wrapper.text()).toContain('Rerank')
    expect(wrapper.text()).toContain('允许回答')
    expect(wrapper.text()).toContain('引用覆盖率')
    expect(wrapper.text()).toContain('查询增强')
    expect(wrapper.text()).toContain('Graph 导航')
    expect(wrapper.text()).toContain('父级上下文')
    expect(wrapper.findAll('[data-trace-stage]')).toHaveLength(10)
  })

  it('makes refusal explicit instead of presenting it as a generic error', () => {
    const trace = structuredClone(traceFixture)
    trace.pipeline!.decision = { status: 'refused', reason: 'no_evidence', threshold: 0.05, confidence: 0 }
    trace.refusal_reason = 'no_evidence'

    const wrapper = mount(RetrievalTrace, { props: { trace } })

    expect(wrapper.get('[data-stage="decision"]').text()).toContain('拒绝回答')
    expect(wrapper.get('[data-stage="decision"]').text()).toContain('没有证据')
  })
})
