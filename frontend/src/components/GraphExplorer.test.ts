import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GraphExplorer from './GraphExplorer.vue'


describe('GraphExplorer', () => {
  it('pairs a scalable graph with an equivalent keyboard-readable evidence table', () => {
    const wrapper = mount(GraphExplorer, { props: { graph: {
      knowledge_base_id: 'default',
      nodes: [
        { node_id: 'a', knowledge_base_id: 'default', type: 'entity', label: 'Alpha', normalized_label: 'alpha', document_id: null, element_id: null, properties: {} },
        { node_id: 'b', knowledge_base_id: 'default', type: 'entity', label: 'Beta', normalized_label: 'beta', document_id: null, element_id: null, properties: {} },
      ],
      edges: [{ edge_id: 'e', knowledge_base_id: 'default', source_node_id: 'a', target_node_id: 'b', relation: 'uses', document_id: 'd', evidence_element_ids: ['el'], evidence_span: 'Alpha uses Beta', confidence: 1, extraction_version: 'native-graph-v1', properties: {} }],
      summary: { node_count: 2, edge_count: 1, evidence_element_count: 1, extraction_version: 'native-graph-v1' },
    } } })

    expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 640 360')
    expect(wrapper.findAll('.graph-node')).toHaveLength(2)
    expect(wrapper.findAll('.graph-node').every((node) => node.attributes('tabindex') === '0')).toBe(true)
    expect(wrapper.get('table').text()).toContain('Alpha')
    expect(wrapper.get('table').text()).toContain('uses')
    expect(wrapper.get('table').text()).toContain('Alpha uses Beta')
  })
})
