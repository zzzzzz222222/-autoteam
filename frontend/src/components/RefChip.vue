<script setup lang="ts">
// A compact reference chip for provenance ids (evidence / insight / trade-off /
// source). When the backend cannot resolve the id it is rendered as a "missing"
// reference instead of inventing a link. When it does resolve and a parent
// provides a locate handler, it becomes a real button (keyboard accessible) that
// scrolls to the corresponding entity.
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    id: string
    label?: string
    resolved?: boolean
    clickable?: boolean
    target?: string | null
  }>(),
  { resolved: true, clickable: false, target: null },
)

const emit = defineEmits<{ select: [target: string | null] }>()

const isButton = computed(() => props.clickable && props.resolved)
const text = computed(() => props.label || props.id)
</script>

<template>
  <button
    v-if="isButton"
    type="button"
    class="at-chip at-chip--link max-w-full align-middle"
    :title="id"
    @click="emit('select', target ?? id)"
  >
    <span class="break-all normal-case">{{ text }}</span>
  </button>
  <span
    v-else
    class="at-chip max-w-full align-middle"
    :class="resolved ? '' : 'at-chip--warn'"
    :title="id"
  >
    <span class="break-all normal-case">{{ text }}</span>
  </span>
</template>
