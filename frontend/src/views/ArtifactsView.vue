<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import { prettyJson } from '@/utils/format'
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
  <div class="mx-auto w-full max-w-[1400px] px-10 py-10">
    <!-- header -->
    <div class="mb-8 flex items-end justify-between gap-6">
      <div>
        <p class="tok-eyebrow mb-2">{{ t('art.flow') }}</p>
        <h1 class="text-[20px] font-semibold tracking-tight text-zinc-900">{{ t('art.flow_title') }}</h1>
        <p class="mt-2 text-[13px] text-zinc-400">
          {{ ordered.length }} {{ t('art.artifacts_count') }} · {{ t('art.flow_sub') }}
        </p>
      </div>
      <p v-if="error" class="text-[15px] text-red-600">{{ error }}</p>
    </div>

    <div class="grid grid-cols-12 gap-10">
      <!-- Collaboration flow: compact 2×2 tiles ordered by dependency depth -->
      <div class="col-span-12">
        <div v-if="ordered.length" class="grid grid-cols-2 gap-4">
          <template v-for="(artifact, idx) in ordered" :key="artifact.artifact_id">
            <button
              type="button"
              class="at-card group flex min-h-[168px] flex-col text-left transition-colors"
              :class="selectedId === artifact.artifact_id
                ? 'border-blue-600 ring-2 ring-blue-600/15'
                : 'hover:border-zinc-400'"
              @click="selectedId = artifact.artifact_id"
            >
              <div class="flex items-start gap-4 px-5 pt-5">
                <span
                  class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border font-mono text-[13px] font-medium"
                  :class="selectedId === artifact.artifact_id
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-zinc-200 text-zinc-500'"
                >
                  {{ String(idx + 1).padStart(2, '0') }}
                </span>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span class="line-clamp-2 text-[15px] font-semibold leading-snug tracking-tight text-zinc-900" :title="artifact.title || artifact.artifact_id">
                      {{ artifact.title || artifact.artifact_id }}
                    </span>
                    <span class="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">
                      {{ artifact.output_type }}
                    </span>
                  </div>
                  <p class="mt-1.5 text-[13px] text-zinc-500">
                    {{ t('art.produced_by') }}
                    <span class="font-medium text-zinc-700">{{ artifact.agent_name }}</span>
                  </p>
                </div>
                <span
                  class="shrink-0 text-[15px] font-medium"
                  :class="selectedId === artifact.artifact_id ? 'text-blue-600' : 'text-zinc-300'"
                >
                  →
                </span>
              </div>
              <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pb-4 pt-3 text-[12px] text-zinc-400">
                <span v-if="artifact.dependencies.length">
                  {{ artifact.dependencies.length }} {{ t('art.upstream') }}
                </span>
                <span v-if="consumersOf(artifact).length" class="min-w-0 truncate">
                  → {{ consumersOf(artifact).map((c) => c.agent_name).join(', ') }}
                </span>
                <span v-if="artifact.source_records.length">{{ artifact.source_records.length }} sources</span>
                <span v-if="artifact.evidence.length">{{ artifact.evidence.length }} evidence</span>
              </div>
            </button>
          </template>
        </div>
        <p v-else-if="!error" class="py-16 text-center text-[15px] text-zinc-400">
          {{ t('art.none') }}
        </p>
      </div>

      <!-- Detail panel (below the list, full width — never blocks the flow) -->
      <div class="col-span-12">
        <p class="tok-eyebrow mb-3">{{ t('art.artifact_label') }}</p>

        <div v-if="selected" class="at-card p-6">
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 class="text-[18px] font-semibold tracking-tight text-zinc-900">
              {{ selected.title || selected.artifact_id }}
            </h2>
            <span class="text-[14px] text-zinc-500">
              {{ selected.agent_name }} · {{ selected.output_type }}
            </span>
          </div>

          <div class="mt-4 flex gap-8 border-y border-zinc-200 py-3">
            <div>
              <p class="tok-metric">{{ selected.source_records.length }}</p>
              <p class="text-[13px] text-zinc-400">{{ t('art.sources') }}</p>
            </div>
            <div>
              <p class="tok-metric">{{ selected.evidence.length }}</p>
              <p class="text-[13px] text-zinc-400">{{ t('art.evidence') }}</p>
            </div>
            <div>
              <p class="tok-metric">{{ selected.dependencies.length }}</p>
              <p class="text-[13px] text-zinc-400">{{ t('art.upstream') }}</p>
            </div>
            <div v-if="consumersOf(selected).length" class="min-w-0">
              <p class="text-[13px] text-zinc-400">{{ t('art.consumed') }}</p>
              <p class="mt-1 text-[14px] text-zinc-700">
                {{ consumersOf(selected).map((c) => c.agent_name).join(', ') }}
              </p>
            </div>
          </div>

          <div class="mt-5 grid grid-cols-12 gap-8">
            <div v-if="Object.keys(selected.structured_data).length" class="col-span-5">
              <p class="text-[12px] font-semibold uppercase tracking-wide text-zinc-400">
                {{ t('art.key_data') }}
              </p>
              <pre class="mt-2 max-h-72 overflow-y-auto rounded bg-zinc-50 p-3 font-mono text-[13px] leading-relaxed text-zinc-600">{{
                prettyJson(selected.structured_data)
              }}</pre>
            </div>

            <div class="col-span-7">
              <p class="text-[12px] font-semibold uppercase tracking-wide text-zinc-400">
                {{ t('art.content') }}
              </p>
              <p class="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap text-[14px] leading-relaxed text-zinc-700">
                {{ selected.content }}
              </p>
            </div>
          </div>

          <div v-if="selected.evidence.length" class="mt-6">
            <p class="text-[12px] font-semibold uppercase tracking-wide text-zinc-400">
              {{ t('art.evidence') }}
            </p>
            <ul class="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
              <li v-for="(ev, i) in selected.evidence" :key="i" class="text-[14px]">
                <p class="text-zinc-700">
                  <span class="font-mono text-[11px] text-zinc-300">#{{ i + 1 }}</span> {{ ev.claim }}
                </p>
                <p class="mt-0.5 pl-5 text-[12px] text-zinc-400">{{ ev.evidence }}</p>
              </li>
            </ul>
          </div>

          <div v-if="selected.source_records.length" class="mt-6">
            <p class="text-[12px] font-semibold uppercase tracking-wide text-zinc-400">
              {{ t('art.sources') }}
            </p>
            <ul class="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
              <li v-for="source in selected.source_records" :key="source.id" class="text-[13px]">
                <a
                  v-if="source.url"
                  :href="source.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-blue-600 underline underline-offset-2 hover:text-blue-700"
                >
                  {{ source.title || source.url }}
                </a>
                <span v-else class="text-zinc-400">
                  {{ source.title }} <span class="text-zinc-300">{{ t('art.offline') }}</span>
                </span>
                <span class="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">
                  {{ source.source_type }}
                </span>
              </li>
            </ul>
          </div>

          <p class="mt-6 text-[12px] text-zinc-400">
            {{ modeHint() === 'real' ? t('art.mode_real') : t('art.mode_offline') }}
          </p>
        </div>

        <p v-else class="at-card p-5 text-[14px] text-zinc-400">
          {{ t('art.select') }}
        </p>
      </div>
    </div>
  </div>
</template>