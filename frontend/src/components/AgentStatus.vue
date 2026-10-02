<script setup lang="ts">
import { computed } from 'vue'
import UnitIcon from '@/components/UnitIcon.vue'
import { useI18n } from '@/i18n'
import type { AgentStatus as S } from '@/types'

const props = withDefaults(
  defineProps<{
    status: S | string
    label?: boolean
  }>(),
  { label: false },
)

const { t } = useI18n()

// Status is conveyed by icon + text + colour (never colour alone).
const meta = computed(() => {
  switch (props.status as S) {
    case 'success':
      return { icon: 'check' as const, cls: 'at-success-text', running: false, key: 'agentstatus.completed' }
    case 'running':
      return { icon: 'dot' as const, cls: 'at-info', running: true, key: 'agentstatus.running' }
    case 'retry':
      return { icon: 'refreshCw' as const, cls: 'at-warn-text', running: true, key: 'agentstatus.retrying' }
    case 'failed':
      return { icon: 'x' as const, cls: 'at-danger-text', running: false, key: 'agentstatus.failed' }
    case 'ready':
      return { icon: 'dot' as const, cls: 'at-dim', running: false, key: 'agentstatus.ready' }
    case 'skipped':
      return { icon: 'dot' as const, cls: 'at-dim', running: false, key: 'agentstatus.skipped' }
    default:
      return { icon: 'dot' as const, cls: 'at-dim', running: false, key: 'agentstatus.pending' }
  }
})
</script>

<template>
  <span class="inline-flex items-center gap-1.5" :title="t(meta.key)">
    <UnitIcon :name="meta.icon" :size="13" :class="[meta.cls, meta.running ? 'at-status-pulse' : '']" />
    <span v-if="label" class="at-t-xs" :class="meta.cls">{{ t(meta.key) }}</span>
    <span v-else class="sr-only">{{ t(meta.key) }}</span>
  </span>
</template>
