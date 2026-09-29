<script setup lang="ts">
// Minimal hand-picked icon set (24px stroke, Lucide-like). Kept deliberately
// tiny — icons assist, they never carry the visual.
import { computed } from 'vue'

defineProps<{
    name:
      | 'box'
      | 'layers'
      | 'workflow'
      | 'fileText'
      | 'search'
      | 'play'
      | 'arrowRight'
      | 'copy'
      | 'download'
      | 'check'
      | 'x'
      | 'refreshCw'
      | 'externalLink'
      | 'settings'
      | 'sparkles'
      | 'chevronDown'
      | 'dot'
      | 'home'
      | 'users'
      | 'gitBranch'
    size?: number
  }>()

const paths: Record<string, string[]> = {
  box: [
    'M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z',
    'M3.3 7l8.7 5 8.7-5',
    'M12 22V12',
  ],
  layers: ['M12 2L2 7l10 5 10-5-10-5z', 'M2 17l10 5 10-5', 'M2 12l10 5 10-5'],
  workflow: ['M3 3h7v7H3z', 'M14 14h7v7h-7z', 'M10 6.5h4a4 4 0 0 1 4 4V14'],
  fileText: [
    'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z',
    'M14 2v6h6',
    'M8 13h8',
    'M8 17h8',
  ],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M21 21l-4.35-4.35'],
  play: ['M5 3l14 9-14 9z'],
  arrowRight: ['M5 12h14', 'M13 6l6 6-6 6'],
  copy: ['M8 8h12v12H8z', 'M4 16V4h12'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  check: ['M20 6L9 17l-5-5'],
  x: ['M18 6L6 18', 'M6 6l12 12'],
  refreshCw: ['M23 4v6h-6', 'M1 20v-6h6', 'M3.51 9a9 9 0 0 1 14.85-3.36L23 10', 'M1 14l4.64 4.36A9 9 0 0 0 20.49 15'],
  externalLink: ['M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6', 'M15 3h6v6', 'M10 14L21 3'],
  settings: [
    'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  ],
  sparkles: ['M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z', 'M19 15l.9 2.4L22 18l-2.1.6L19 21l-.9-2.4L16 18l2.1-.6z'],
  chevronDown: ['M6 9l6 6 6-6'],
  dot: ['M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0'],
  home: ['M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M9 22V12h6v10'],
  users: ['M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2', 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M23 21v-2a4 4 0 0 0-3-3.87', 'M16 3.13a4 4 0 0 1 0 7.75'],
  gitBranch: ['M6 3v12', 'M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', 'M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M6 21a9 9 0 0 0 9-9'],
}

const viewBox = computed(() => '0 0 24 24')
</script>

<template>
  <svg
    :width="size ?? 16"
    :height="size ?? 16"
    :viewBox="viewBox"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in paths[name] ?? []" :key="i" :d="d" />
  </svg>
</template>