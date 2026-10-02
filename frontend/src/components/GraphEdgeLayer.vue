<script setup lang="ts">
// Renders the real DAG dependency edges as an SVG overlay on top of the layered
// Agent columns. Pure presentational: the parent measures node positions and
// passes ready-to-draw shapes, so this component never invents geometry or
// relationships. Edges are aria-hidden — the accessible fallback is the text
// dependency list rendered by the parent.
import type { GraphEdgeShape } from '@/types'

defineProps<{
  width: number
  height: number
  edges: GraphEdgeShape[]
}>()
</script>

<template>
  <svg
    v-if="edges.length && width > 0 && height > 0"
    class="at-graph__edges"
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <marker
        id="at-edge-arrow"
        viewBox="0 0 8 8"
        refX="7"
        refY="4"
        markerWidth="7"
        markerHeight="7"
        orient="auto"
      >
        <path d="M0,0 L8,4 L0,8 Z" class="at-graph__arrow" />
      </marker>
      <marker
        id="at-edge-arrow-active"
        viewBox="0 0 8 8"
        refX="7"
        refY="4"
        markerWidth="7"
        markerHeight="7"
        orient="auto"
      >
        <path d="M0,0 L8,4 L0,8 Z" class="at-graph__arrow is-active" />
      </marker>
    </defs>
    <path
      v-for="edge in edges"
      :key="edge.id"
      :d="edge.d"
      fill="none"
      class="at-graph__edge"
      :class="{ 'is-active': edge.active, 'is-dim': edge.dim }"
      :marker-end="edge.active ? 'url(#at-edge-arrow-active)' : 'url(#at-edge-arrow)'"
    />
  </svg>
</template>
