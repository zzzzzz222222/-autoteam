<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import type { ArtifactDto } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const artifacts = ref<ArtifactDto[]>([])
const error = ref<string | null>(null)
const selectedId = ref<string | null>(null)

// ordered by dependency depth = collaboration flow
const ordered = computed(() => {
  const ids = new Set(artifacts.value.map((a) => a.artifact_id))
  const depth = new Map<string, number>()
  const computeDepth = (a: ArtifactDto, seen: Set<string>): number => {
    if (depth.has(a.artifact_id)) return depth.get(a.artifact_id)!
    if (seen.has(a.artifact_id)) return 0
    seen.add(a.artifact_id)
    const up = a.dependencies.filter((d) => ids.has(d))
    const value = up.length ? 1 + Math.max(...up.map((d) => {
      const upArt = artifacts.value.find((x) => x.artifact_id === d)
      return upArt ? computeDepth(upArt, seen) : 0
    })) : 0
    depth.set(a.artifact_id, value)
    return value
  }
  for (const a of artifacts.value) computeDepth(a, new Set())
  return [...artifacts.value].sort(
    (x, y) => (depth.get(x.artifact_id) ?? 0) - (depth.get(y.artifact_id) ?? 0),
  )
})

const selected = computed(() =>
  ordered.value.find((a) => a.artifact_id === selectedId.value) ?? null,
)

// consumers = artifacts that list this artifact as dependency
function consumersOf(artifact: ArtifactDto): ArtifactDto[] {
  return ordered.value.filter((a) => a.dependencies.includes(artifact.artifact_id))
}

async function load() {
  try {
    const res = await api.getArtifacts(props.taskId)
    artifacts.value = res.artifacts
    if (!selectedId.value && res.artifacts.length) {
      selectedId.value = res.artifacts[0].artifact_id
    }
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

function modeHint(): 'real' | 'offline' {
  return store.current?.mode === 'real' ? 'real' : 'offline'
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-8 py-8">
    <p class="tok-eyebrow mb-6">{{ t('art.flow') }}</p>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <!-- Collaboration flow (vertical, dividers instead of cards) -->
    <div v-if="ordered.length" class="max-w-2xl">
      <template v-for="(artifact, idx) in ordered" :key="artifact.artifact_id">
        <button
          type="button"
          class="group flex w-full items-start gap-4 py-4 text-left"
          @click="selectedId = artifact.artifact_id"
        >
          <span
            class="mt-1 inline-block h-2 w-2 shrink-0 rounded-full border"
            :class="selectedId === artifact.artifact_id ? 'border-zinc-900 bg-zinc-900' : 'border-zinc-300'"
          />
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2.5">
              <span
                class="text-[14px] font-medium"
                :class="selectedId === artifact.artifact_id ? 'text-zinc-900' : 'text-zinc-700'"
              >
                {{ artifact.title || artifact.artifact_id }}
              </span>
              <span class="text-[11px] uppercase tracking-wide text-zinc-400">
                {{ artifact.output_type }}
              </span>
            </div>
            <p class="mt-0.5 text-[12px] text-zinc-400">
              {{ artifact.agent_name }}
              <span v-if="consumersOf(artifact).length" class="text-zinc-300">
                · {{ t('art.consumed_by') }} {{ consumersOf(artifact).map((c) => c.agent_name).join(', ') }}
              </span>
              <span v-if="artifact.source_records.length" class="text-zinc-300">
                · {{ artifact.source_records.length }} sources
              </span>
            </p>
          </div>
          <span class="shrink-0 font-mono text-[11px] text-zinc-300">→</span>
        </button>
        <div v-if="idx < ordered.length - 1" class="tok-hairline" />
      </template>
    </div>
    <p v-else-if="!error" class="py-12 text-sm text-zinc-400">
      {{ t('art.none') }}
    </p>

    <!-- Detail drawer (right) -->
    <div
      v-if="selected"
      class="fixed inset-y-0 right-0 z-20 w-[440px] overflow-y-auto border-l border-zinc-200 bg-white px-7 py-8 shadow-lg"
    >
      <div class="flex items-baseline justify-between">
        <p class="tok-eyebrow">{{ t('art.artifact_label') }}</p>
        <button
          type="button"
          class="text-zinc-400 transition-colors hover:text-zinc-900"
          @click="selectedId = null"
          aria-label="close"
        >
          ✕
        </button>
      </div>

      <h2 class="mt-3 text-lg font-semibold tracking-tight text-zinc-900">
        {{ selected.title || selected.artifact_id }}
      </h2>
      <p class="mt-0.5 text-[13px] text-zinc-500">
        {{ selected.agent_name }} · {{ selected.output_type }}
      </p>

      <div class="mt-5 flex gap-6 border-y border-zinc-200 py-3 text-[12px]">
        <div>
          <p class="font-mono text-base font-medium text-zinc-900">{{ selected.source_records.length }}</p>
          <p class="text-zinc-400">{{ t('art.sources') }}</p>
        </div>
        <div>
          <p class="font-mono text-base font-medium text-zinc-900">{{ selected.evidence.length }}</p>
          <p class="text-zinc-400">{{ t('art.evidence') }}</p>
        </div>
        <div>
          <p class="font-mono text-base font-medium text-zinc-900">{{ selected.dependencies.length }}</p>
          <p class="text-zinc-400">{{ t('art.upstream') }}</p>
        </div>
      </div>

      <div v-if="selected.dependencies.length" class="mt-4">
        <p class="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          {{ t('art.consumed') }}
        </p>
        <p class="mt-1 text-[13px] text-zinc-600">
          {{ consumersOf(selected).map((c) => c.agent_name).join(', ') || '—' }}
        </p>
      </div>

      <div v-if="Object.keys(selected.structured_data).length" class="mt-5">
        <p class="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          {{ t('art.key_data') }}
        </p>
        <pre class="mt-1.5 overflow-x-auto rounded bg-zinc-50 p-3 font-mono text-[11px] leading-relaxed text-zinc-600">{{
          JSON.stringify(selected.structured_data, null, 2)
        }}</pre>
      </div>

      <div class="mt-5">
        <p class="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          {{ t('art.content') }}
        </p>
        <p class="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-700">
          {{ selected.content }}
        </p>
      </div>

      <div v-if="selected.evidence.length" class="mt-6">
        <p class="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          {{ t('art.evidence') }}
        </p>
        <ul class="mt-2 space-y-2.5">
          <li v-for="(ev, i) in selected.evidence" :key="i" class="text-[13px]">
            <p class="text-zinc-700">
              <span class="font-mono text-[10px] text-zinc-300">#{{ i + 1 }}</span> {{ ev.claim }}
            </p>
            <p class="mt-0.5 pl-5 text-[11px] text-zinc-400">{{ ev.evidence }}</p>
          </li>
        </ul>
      </div>

      <div v-if="selected.source_records.length" class="mt-6">
        <p class="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
          {{ t('art.sources') }}
        </p>
        <ul class="mt-2 space-y-1.5 text-[12px]">
          <li v-for="source in selected.source_records" :key="source.id">
            <a
              v-if="source.url"
              :href="source.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-zinc-600 underline underline-offset-2 hover:text-zinc-900"
            >
              {{ source.title || source.url }}
            </a>
            <span v-else class="text-zinc-400">
              {{ source.title }} <span class="text-zinc-300">(offline)</span>
            </span>
            <span class="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
              {{ source.source_type }}
            </span>
          </li>
        </ul>
      </div>

      <p class="mt-6 text-[11px] text-zinc-300">
        {{ modeHint() === 'real' ? t('art.mode_real') : t('art.mode_offline') }}
      </p>
    </div>
  </div>
</template>