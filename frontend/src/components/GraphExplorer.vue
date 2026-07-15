<script setup lang="ts">
import { computed } from 'vue'

import type { KnowledgeGraph } from '../api'


const props = defineProps<{ graph: KnowledgeGraph }>()
const visibleNodes = computed(() => props.graph.nodes.slice(0, 24))
const positions = computed(() => {
  const count = Math.max(visibleNodes.value.length, 1)
  return Object.fromEntries(visibleNodes.value.map((node, index) => {
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2
    const radius = count <= 6 ? 112 : 142
    return [node.node_id, { x: 320 + Math.cos(angle) * radius, y: 180 + Math.sin(angle) * radius }]
  }))
})
const visibleEdges = computed(() => props.graph.edges.filter((edge) => positions.value[edge.source_node_id] && positions.value[edge.target_node_id]).slice(0, 40))

function shortLabel(value: string) {
  return value.length > 18 ? `${value.slice(0, 17)}…` : value
}
</script>

<template>
  <section class="graph-explorer" aria-labelledby="graph-explorer-title">
    <header class="subsection-heading stacked-heading">
      <div><h3 id="graph-explorer-title">证据图谱</h3><span>{{ graph.summary.extraction_version }}</span></div>
      <span class="status-badge neutral">{{ graph.summary.node_count }} nodes · {{ graph.summary.edge_count }} edges</span>
    </header>
    <div v-if="!graph.nodes.length" class="empty-state compact-empty"><strong>暂无图谱证据</strong><p>重建文档索引后，显式关系会连同 provenance 进入此处。</p></div>
    <template v-else>
      <svg class="graph-canvas" viewBox="0 0 640 360" role="img" aria-labelledby="graph-svg-title graph-svg-desc">
        <title id="graph-svg-title">当前知识库的证据关系图</title>
        <desc id="graph-svg-desc">节点表示文档、元素和实体，连线表示带原始证据的关系。下方表格提供等价键盘视图。</desc>
        <line
          v-for="edge in visibleEdges"
          :key="edge.edge_id"
          :x1="positions[edge.source_node_id].x"
          :y1="positions[edge.source_node_id].y"
          :x2="positions[edge.target_node_id].x"
          :y2="positions[edge.target_node_id].y"
          class="graph-edge"
        />
        <g
          v-for="node in visibleNodes"
          :key="node.node_id"
          :transform="`translate(${positions[node.node_id].x} ${positions[node.node_id].y})`"
          tabindex="0"
          role="img"
          :aria-label="`${node.type}: ${node.label}`"
          :class="['graph-node', `node-${node.type}`]"
        >
          <circle r="27" />
          <text text-anchor="middle" y="42">{{ shortLabel(node.label) }}</text>
        </g>
      </svg>
      <div class="graph-table-wrap" tabindex="0" aria-label="图谱关系可滚动表格">
        <table>
          <caption>可审查关系与原文证据</caption>
          <thead><tr><th scope="col">源</th><th scope="col">关系</th><th scope="col">目标</th><th scope="col">证据</th></tr></thead>
          <tbody>
            <tr v-for="edge in graph.edges.slice(0, 80)" :key="edge.edge_id">
              <td>{{ graph.nodes.find((node) => node.node_id === edge.source_node_id)?.label || edge.source_node_id }}</td>
              <td>{{ edge.relation }}</td>
              <td>{{ graph.nodes.find((node) => node.node_id === edge.target_node_id)?.label || edge.target_node_id }}</td>
              <td>{{ edge.evidence_span || `${edge.evidence_element_ids.length} 个元素` }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
