<script setup lang="ts">
import { computed } from 'vue'
import type { AgentStatus } from '@/types'

const props = defineProps<{ status: AgentStatus | string }>()

const meta = computed(() => {
  const s = props.status
  switch (s) {
    case 'success':
      return { glyph: '✓', label: 'SUCCESS', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
    case 'running':
      return { glyph: '◌', label: 'RUNNING', cls: 'bg-sky-50 text-sky-700 border-sky-200' }
    case 'ready':
      return { glyph: '○', label: 'READY', cls: 'bg-zinc-50 text-zinc-500 border-zinc-200' }
    case 'retry':
      return { glyph: '↻', label: 'RETRY', cls: 'bg-amber-50 text-amber-700 border-amber-200' }
    case 'failed':
      return { glyph: '×', label: 'FAILED', cls: 'bg-red-50 text-red-700 border-red-200' }
    case 'skipped':
      return { glyph: '⊘', label: 'SKIPPED', cls: 'bg-zinc-50 text-zinc-400 border-zinc-200' }
    default:
      return { glyph: '○', label: (s || 'PENDING').toUpperCase(), cls: 'bg-zinc-50 text-zinc-500 border-zinc-200' }
  }
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none"
    :class="meta.cls"
  >
    <span aria-hidden="true">{{ meta.glyph }}</span>
    {{ meta.label }}
  </span>
</template>