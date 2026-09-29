<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useI18n } from '@/i18n'
import type { ArtifactDto } from '@/types'

const props = defineProps<{ taskId: string }>()
const { t } = useI18n()
const artifacts = ref<ArtifactDto[]>([])
const error = ref<string | null>(null)
const expandedId = ref<string | null>(null)

async function load() {
  try {
    const res = await api.getArtifacts(props.taskId)
    artifacts.value = res.artifacts
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

const ordered = computed(() => {
  // Order by execution flow: dependencies first (topological-ish approximation)
  const ids = new Set(artifacts.value.map((a) => a.artifact_id))
  const degree = new Map<string, number>()
  for (const a of artifacts.value) {
    degree.set(a.artifact_id, a.dependencies.filter((d) => ids.has(d)).length)
  }
  return [...artifacts.value].sort((x, y) => (degree.get(x.artifact_id) ?? 0) - (degree.get(y.artifact_id) ?? 0))
})

function renderMarkdown(md: string): string {
  return escapeHtml(md)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
</script>

<template>
  <div class="space-y-4">
    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <!-- Collaboration chain -->
    <div v-if="ordered.length" class="flex flex-wrap items-stretch gap-3">
      <template v-for="(artifact, idx) in ordered" :key="artifact.artifact_id">
        <div
          class="rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm w-56"
          :class="{ 'border-zinc-700': expandedId === artifact.artifact_id }"
        >
          <p class="font-medium text-zinc-800">{{ artifact.title || artifact.artifact_id }}</p>
          <p class="mt-1 text-[11px] text-zinc-500">
            {{ artifact.agent_name }} · {{ artifact.output_type }}
          </p>
          <p class="mt-1 text-[11px] text-zinc-400">
            {{ t('art.sources') }} {{ artifact.source_records.length }} · {{ t('art.evidence') }} {{ artifact.evidence.length }}
          </p>
          <button
            type="button"
            class="mt-2 text-[11px] font-medium text-zinc-500 underline-offset-2 hover:text-zinc-900 hover:underline"
            @click="expandedId = expandedId === artifact.artifact_id ? null : artifact.artifact_id"
          >
            {{ expandedId === artifact.artifact_id ? t('art.collapse') : t('art.expand') }}
          </button>
        </div>
        <span v-if="idx < ordered.length - 1" class="self-center text-zinc-400">→</span>
      </template>
    </div>
    <p v-else-if="!error" class="rounded-lg border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-400">
      {{ t('art.none') }}
    </p>

    <!-- Expanded artifact detail -->
    <div v-for="artifact in ordered" :key="artifact.artifact_id">
      <div v-if="expandedId === artifact.artifact_id" class="rounded-lg border border-zinc-200 bg-white p-4">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <p class="font-semibold text-zinc-900">{{ artifact.title }}</p>
            <p class="text-xs text-zinc-500">{{ artifact.agent_name }} · {{ artifact.output_type }}</p>
          </div>
          <span class="text-xs text-zinc-400">{{ artifact.created_at }}</span>
        </div>

        <div v-if="artifact.dependencies.length" class="mb-3 text-xs text-zinc-500">
          <span class="font-medium text-zinc-600">{{ t('art.upstream') }}:</span>
          {{ artifact.dependencies.join(', ') }}
        </div>

        <div class="prose-markdown text-sm text-zinc-700" v-html="renderMarkdown(artifact.content)"></div>

        <div v-if="Object.keys(artifact.structured_data).length" class="mt-3 rounded bg-zinc-50 p-3 text-xs">
          <p class="mb-1 font-medium text-zinc-600">{{ t('art.key_data') }}</p>
          <pre class="whitespace-pre-wrap text-zinc-600">{{ JSON.stringify(artifact.structured_data, null, 2) }}</pre>
        </div>

        <div v-if="artifact.source_records.length" class="mt-3">
          <p class="mb-1 text-xs font-medium text-zinc-600">{{ t('art.sources') }}</p>
          <ol class="space-y-1 text-xs text-zinc-600">
            <li v-for="source in artifact.source_records" :key="source.id">
              {{ source.title }}
              <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="text-zinc-400 underline">
                ({{ source.url.slice(0, 60) }})
              </a>
              <span v-else class="text-zinc-400">{{ t('art.offline') }}</span>
              <span class="ml-1 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">{{ source.source_type }}</span>
            </li>
          </ol>
        </div>

        <div v-if="artifact.evidence.length" class="mt-3">
          <p class="mb-1 text-xs font-medium text-zinc-600">{{ t('art.evidence') }}</p>
          <ul class="space-y-1 text-xs text-zinc-600">
            <li v-for="(ev, i) in artifact.evidence" :key="i">
              <span class="text-zinc-400">#{{ i + 1 }}</span> {{ ev.claim }}
              <span class="text-zinc-400">— {{ ev.evidence.slice(0, 120) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>