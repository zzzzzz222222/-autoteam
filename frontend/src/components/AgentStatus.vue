<script setup lang="ts">
import { computed } from 'vue'
import type { AgentStatus as S } from '@/types'

const props = withDefaults(
  defineProps<{
    status: S | string
    label?: boolean
  }>(),
  { label: false },
)

const meta = computed(() => {
  const s = props.status as S
  switch (s) {
    case 'success':
      return { glyph: '✓', cls: 'text-emerald-600', running: false, label: 'completed' }
    case 'running':
      return { glyph: '●', cls: 'text-blue-600', running: true, label: 'running' }
    case 'ready':
      return { glyph: '○', cls: 'text-zinc-400', running: false, label: 'ready' }
    case 'retry':
      return { glyph: '↻', cls: 'text-amber-600', running: true, label: 'retrying' }
    case 'failed':
      return { glyph: '✕', cls: 'text-red-600', running: false, label: 'failed' }
    case 'skipped':
      return { glyph: '⊘', cls: 'text-zinc-300', running: false, label: 'skipped' }
    default:
      return { glyph: '○', cls: 'text-zinc-300', running: false, label: (s || 'pending').toLowerCase() }
  }
})
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-xs">
    <span
      class="inline-block h-2 w-2 rounded-full border border-current"
      :class="[meta.cls, meta.running ? 'at-status-pulse' : '']"
      aria-hidden="true"
    />
    <span v-if="label" class="text-zinc-500">{{ meta.label }}</span>
  </span>
</template>