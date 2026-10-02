<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'
import { hostOf, prettyJson, safeHttpUrl, truncateMiddle } from '@/utils/format'
import type { ArtifactDto } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const artifacts = ref<ArtifactDto[]>([])
const error = ref<string | null>(null)
const selectedId = ref<string | null>(null)
const highlightedId = ref('')

const byId = computed(() => {
  const map = new Map<string, ArtifactDto>()
  for (const a of artifacts.value) map.set(a.artifact_id, a)
  return map
})

// Real dependency depth, derived from the backend `dependencies` edges only
// (entry artifacts = 0). Used instead of a rank-like running index (M9).
const depthById = computed(() => {
  const depth = new Map<string, number>()
  const visit = (a: ArtifactDto, seen: Set<string>): number => {
    const cached = depth.get(a.artifact_id)
    if (cached !== undefined) return cached
    if (seen.has(a.artifact_id)) return 0
    seen.add(a.artifact_id)
    const ups = a.dependencies.filter((d) => byId.value.has(d))
    const value = ups.length
      ? 1 + Math.max(...ups.map((d) => visit(byId.value.get(d) as ArtifactDto, seen)))
      : 0
    depth.set(a.artifact_id, value)
    return value
  }
  for (const a of artifacts.value) visit(a, new Set())
  return depth
})

// Collaboration flow ordered by depth.
const ordered = computed(() =>
  [...artifacts.value].sort(
    (x, y) => (depthById.value.get(x.artifact_id) ?? 0) - (depthById.value.get(y.artifact_id) ?? 0),
  ),
)

const selected = computed(() => (selectedId.value ? byId.value.get(selectedId.value) ?? null : null))

// Upstream / downstream are real artifact-level edges (never agent-level faked).
function upstreamOf(a: ArtifactDto): ArtifactDto[] {
  return a.dependencies.map((d) => byId.value.get(d)).filter((x): x is ArtifactDto => !!x)
}
function missingDepsOf(a: ArtifactDto): string[] {
  return a.dependencies.filter((d) => !byId.value.has(d))
}
function consumersOf(a: ArtifactDto): ArtifactDto[] {
  return ordered.value.filter((x) => x.dependencies.includes(a.artifact_id))
}
function depthOf(id: string): number {
  return depthById.value.get(id) ?? 0
}

async function load() {
  try {
    const res = await api.getArtifacts(props.taskId)
    artifacts.value = res.artifacts
    selectedId.value = res.artifacts.length ? res.artifacts[0].artifact_id : null
  } catch (err) {
    error.value = String(err)
  }
}
onMounted(load)
watch(() => props.taskId, load)

function locateArtifact(id: string) {
  selectedId.value = id
  void nextTick(() => {
    const el = document.getElementById(`artifact-tile-${id}`) ?? document.getElementById('artifact-detail')
    if (!el) return
    const reduce =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' })
    highlightedId.value = `artifact-tile-${id}`
    window.setTimeout(() => (highlightedId.value = ''), 1900)
  })
}
function isHighlighted(id: string): boolean {
  return highlightedId.value === id
}

function modeHint(): 'real' | 'offline' {
  return store.current?.mode === 'real' ? 'real' : 'offline'
}
function href(url?: string): string | null {
  return safeHttpUrl(url)
}
function sourceLinkLabel(source: { title: string; url: string; id: string }): string {
  return source.title || hostOf(source.url) || truncateMiddle(source.url, 48) || source.id
}
function artifactLabel(a: ArtifactDto): string {
  return a.title || a.artifact_id
}
</script>

<template>
  <div class="mx-auto w-full max-w-[1400px] px-6 py-8 md:px-10 md:py-10">
    <!-- header -->
    <div class="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="at-h2 at-t-xl">{{ t('art.flow_title') }}</h1>
        <p class="mt-2 at-t-xs at-dim">
          {{ ordered.length }} {{ t('art.artifacts_count') }} · {{ t('art.flow_sub') }}
        </p>
      </div>
      <p v-if="error" role="alert" class="at-t-base at-danger-text">{{ error }} <span class="at-t-xs at-muted">{{ t('common.error_reload_hint') }}</span></p>
    </div>

    <!-- Collaboration flow -->
    <section class="mb-10">
      <h2 class="at-eyebrow mb-3">{{ t('art.flow') }}</h2>

      <div v-if="ordered.length" class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="artifact in ordered"
          :id="`artifact-tile-${artifact.artifact_id}`"
          :key="artifact.artifact_id"
          type="button"
          class="at-card flex min-h-[164px] flex-col text-left transition-colors"
          :class="[
            selectedId === artifact.artifact_id ? 'border-[var(--at-info)]' : 'hover:border-[var(--at-border-strong)]',
            isHighlighted(`artifact-tile-${artifact.artifact_id}`) ? 'at-locate-flash' : '',
          ]"
          :aria-pressed="selectedId === artifact.artifact_id"
          @click="selectedId = artifact.artifact_id"
        >
          <div class="flex items-start gap-3 px-5 pt-5">
            <span
              class="at-chip shrink-0"
              :class="selectedId === artifact.artifact_id ? 'at-chip--info' : ''"
              :aria-label="`${t('art.depth')} ${depthOf(artifact.artifact_id)}`"
            >
              {{ t('art.depth') }} {{ depthOf(artifact.artifact_id) }}
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span class="line-clamp-2 at-t-md font-semibold leading-snug at-fg" :title="artifactLabel(artifact)">
                  {{ artifactLabel(artifact) }}
                </span>
                <span class="at-chip">{{ artifact.output_type }}</span>
              </div>
              <p class="mt-1.5 at-t-xs at-dim">
                {{ t('art.produced_by') }} <span class="at-muted">{{ artifact.agent_name }}</span>
              </p>
            </div>
          </div>
          <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pb-4 pt-3 font-mono at-t-xs at-dim">
            <span>{{ upstreamOf(artifact).length }} {{ t('art.upstream') }}</span>
            <span>{{ consumersOf(artifact).length }} {{ t('art.downstream_title') }}</span>
            <span v-if="artifact.source_records.length">{{ artifact.source_records.length }} {{ t('art.sources') }}</span>
            <span v-if="artifact.evidence.length">{{ artifact.evidence.length }} {{ t('art.evidence') }}</span>
          </div>
        </button>
      </div>
      <div v-else-if="!error" class="at-card flex flex-col items-center gap-2 py-16 text-center">
        <UnitIcon name="inbox" :size="22" class="at-dim" />
        <p class="at-t-base at-muted">{{ t('art.none') }}</p>
      </div>
    </section>

    <!-- Detail -->
    <section id="artifact-detail">
      <h2 class="at-eyebrow mb-3">{{ t('art.artifact_label') }}</h2>

      <div v-if="selected" class="at-card p-5 md:p-6">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 class="at-t-lg font-semibold at-fg">{{ artifactLabel(selected) }}</h3>
          <span class="at-t-sm"><span class="at-muted">{{ selected.agent_name }}</span> <span class="at-dim">{{ selected.output_type }}</span></span>
        </div>

        <div class="at-border-b at-border-t mt-4 flex flex-wrap gap-8 py-3">
          <div>
            <p class="at-metric">{{ selected.source_records.length }}</p>
            <p class="at-t-xs at-dim">{{ t('art.sources') }}</p>
          </div>
          <div>
            <p class="at-metric">{{ selected.evidence.length }}</p>
            <p class="at-t-xs at-dim">{{ t('art.evidence') }}</p>
          </div>
          <div>
            <p class="at-metric">{{ depthOf(selected.artifact_id) }}</p>
            <p class="at-t-xs at-dim">{{ t('art.depth') }}</p>
          </div>
        </div>

        <!-- Upstream / downstream (real artifact-level edges) -->
        <div class="mt-5 grid grid-cols-12 gap-6">
          <div class="col-span-12 md:col-span-6">
            <h4 class="at-eyebrow mb-2">{{ t('art.upstream_title') }}</h4>
            <ul v-if="upstreamOf(selected).length || missingDepsOf(selected).length" class="flex flex-wrap gap-1.5">
              <li v-for="up in upstreamOf(selected)" :key="up.artifact_id">
                <button type="button" class="at-chip at-chip--link" @click="locateArtifact(up.artifact_id)">
                  {{ artifactLabel(up) }}
                </button>
              </li>
              <li v-for="mid in missingDepsOf(selected)" :key="mid">
                <span class="at-chip at-chip--warn">{{ mid }} · {{ t('art.ref_missing') }}</span>
              </li>
            </ul>
            <p v-else class="at-t-xs at-dim">{{ t('art.no_upstream') }}</p>
          </div>

          <div class="col-span-12 md:col-span-6">
            <h4 class="at-eyebrow mb-2">{{ t('art.downstream_title') }}</h4>
            <ul v-if="consumersOf(selected).length" class="flex flex-wrap gap-1.5">
              <li v-for="down in consumersOf(selected)" :key="down.artifact_id">
                <button type="button" class="at-chip at-chip--link" @click="locateArtifact(down.artifact_id)">
                  {{ artifactLabel(down) }}
                </button>
              </li>
            </ul>
            <p v-else class="at-t-xs at-dim">{{ t('art.no_downstream') }}</p>
          </div>
        </div>
        <p class="mt-2 at-t-xs at-dim">{{ t('art.locate_hint') }}</p>

        <!-- Content -->
        <div class="mt-5 grid grid-cols-12 gap-6">
          <div v-if="Object.keys(selected.structured_data).length" class="col-span-12 lg:col-span-5">
            <h4 class="at-eyebrow mb-2">{{ t('art.key_data') }}</h4>
            <pre class="at-inset max-h-72 overflow-y-auto p-3 font-mono at-t-xs leading-relaxed at-muted">{{ prettyJson(selected.structured_data) }}</pre>
          </div>

          <div class="col-span-12 lg:col-span-7">
            <h4 class="at-eyebrow mb-2">{{ t('art.content') }}</h4>
            <p class="max-h-72 overflow-y-auto whitespace-pre-wrap at-t-sm leading-relaxed at-muted">{{ selected.content }}</p>
          </div>
        </div>

        <div v-if="selected.evidence.length" class="mt-6">
          <h4 class="at-eyebrow mb-2">{{ t('art.evidence') }}</h4>
          <ul class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <li v-for="(ev, i) in selected.evidence" :key="ev.evidence_id || (ev.source_id + '|') + i" class="at-inset p-3 at-t-sm">
              <p class="at-fg">
                <span class="font-mono at-t-xs at-dim">#{{ i + 1 }}</span> {{ ev.claim }}
              </p>
              <p v-if="ev.evidence" class="mt-1 at-t-xs at-dim">{{ ev.evidence }}</p>
            </li>
          </ul>
        </div>

        <div v-if="selected.source_records.length" class="mt-6">
          <h4 class="at-eyebrow mb-2">{{ t('art.sources') }}</h4>
          <ul class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
            <li v-for="source in selected.source_records" :key="source.id" class="min-w-0 at-t-sm">
              <a
                v-if="href(source.url)"
                :href="href(source.url) || undefined"
                target="_blank"
                rel="noopener noreferrer"
                class="break-all at-info underline underline-offset-2"
                :title="source.url"
              >
                {{ sourceLinkLabel(source) }}
              </a>
              <span v-else class="at-muted">{{ source.title || source.id }} <span class="at-dim">{{ t('art.offline') }}</span></span>
              <span class="at-chip ml-2">{{ source.source_type }}</span>
            </li>
          </ul>
        </div>

        <p class="mt-6 at-t-xs at-dim">
          {{ modeHint() === 'real' ? t('art.mode_real') : t('art.mode_offline') }}
        </p>
      </div>

      <div v-else class="at-card p-5 at-t-sm at-dim">{{ t('art.select') }}</div>
    </section>
  </div>
</template>
