<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import AgentStatus from '@/components/AgentStatus.vue'
import UnitIcon from '@/components/UnitIcon.vue'
import GraphEdgeLayer from '@/components/GraphEdgeLayer.vue'
import type { GraphEdgeShape, TeamResponse } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const team = ref<TeamResponse | null>(null)
const selectedAgentId = ref<string | null>(null)
const error = ref<string | null>(null)

const executionReached = computed(
  () =>
    store.current != null &&
    (store.current.started_at != null ||
      store.current.status === 'running' ||
      store.current.status === 'success'),
)

const formation = computed(() => [
  { label: t('tf.task_understanding'), done: true },
  { label: t('tf.capability_discovery'), done: !!team.value?.explanation },
  { label: t('tf.role_allocation'), done: team.value != null },
  { label: t('tf.agent_factory'), done: team.value != null },
  { label: t('tf.dag_validation'), done: team.value != null },
  { label: t('tf.execution'), done: executionReached.value },
])

async function load() {
  try {
    team.value = await api.getTeam(props.taskId)
    selectedAgentId.value = team.value.agents.length ? team.value.agents[0].id : null
    await nextTick()
    observeAndMeasure()
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

const selectedAgent = computed(
  () => team.value?.agents.find((a) => a.id === selectedAgentId.value) ?? null,
)
const layerColumns = computed(() => team.value?.layers ?? [])

// stable business key for a layer (M7 — no index keys)
function layerKey(layer: string[]): string {
  return layer.join('|')
}
function agentsInLayer(layer: string[]) {
  return team.value?.agents.filter((a) => layer.includes(a.id)) ?? []
}
function layerOf(agentId: string): number {
  const layers = team.value?.layers ?? []
  for (let i = 0; i < layers.length; i++) if (layers[i].includes(agentId)) return i
  return 0
}
function agentName(id: string): string {
  return team.value?.agents.find((a) => a.id === id)?.name ?? id
}

// ---------------------------------------------------------------------------
// M1 — real DAG edges. Edges come from the backend `edges` field only; an edge
// whose endpoints are not real agents is surfaced as a missing reference in the
// text fallback, never drawn.
// ---------------------------------------------------------------------------
const knownAgentIds = computed(() => new Set((team.value?.agents ?? []).map((a) => a.id)))
const allEdges = computed(() => team.value?.edges ?? [])
const realEdges = computed(() =>
  allEdges.value.filter((e) => knownAgentIds.value.has(e.source) && knownAgentIds.value.has(e.target)),
)
const missingEdges = computed(() =>
  allEdges.value.filter((e) => !knownAgentIds.value.has(e.source) || !knownAgentIds.value.has(e.target)),
)
function isIncident(edge: { source: string; target: string }): boolean {
  return selectedAgentId.value != null && (edge.source === selectedAgentId.value || edge.target === selectedAgentId.value)
}

// ---------------------------------------------------------------------------
// Edge geometry — measured from the rendered nodes (never inferred from data).
// ---------------------------------------------------------------------------
const graphInner = ref<HTMLElement | null>(null)
const nodeRects = ref<Record<string, { left: number; right: number; centerY: number }>>({})
const svgSize = ref({ width: 0, height: 0 })

let rafId = 0
function measure() {
  cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => {
    const inner = graphInner.value
    if (!inner) return
    const base = inner.getBoundingClientRect()
    const rects: Record<string, { left: number; right: number; centerY: number }> = {}
    inner.querySelectorAll<HTMLElement>('[data-agent-id]').forEach((el) => {
      const id = el.dataset.agentId
      if (!id) return
      const r = el.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) return
      rects[id] = {
        left: r.left - base.left,
        right: r.right - base.left,
        centerY: r.top - base.top + r.height / 2,
      }
    })
    nodeRects.value = rects
    svgSize.value = {
      width: Math.max(inner.offsetWidth, inner.scrollWidth),
      height: Math.max(inner.offsetHeight, inner.scrollHeight),
    }
  })
}

const edgeShapes = computed<GraphEdgeShape[]>(() => {
  const rects = nodeRects.value
  const shapes: GraphEdgeShape[] = []
  for (const edge of realEdges.value) {
    const source = rects[edge.source]
    const target = rects[edge.target]
    if (!source || !target) continue
    const x1 = source.right
    const y1 = source.centerY
    const x2 = target.left - 8 // leave room for the arrow head
    const y2 = target.centerY
    const dx = Math.max(28, Math.abs(x2 - x1) / 2)
    shapes.push({
      id: `${edge.source}->${edge.target}`,
      d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
      active: isIncident(edge),
      dim: selectedAgentId.value != null && !isIncident(edge),
    })
  }
  return shapes
})

let resizeObserver: ResizeObserver | null = null
let onWindowResize: (() => void) | null = null

function observeAndMeasure() {
  if (resizeObserver && graphInner.value) {
    resizeObserver.disconnect()
    resizeObserver.observe(graphInner.value)
  }
  measure()
}

onMounted(() => {
  onWindowResize = () => measure()
  window.addEventListener('resize', onWindowResize)
  if (typeof ResizeObserver !== 'undefined') resizeObserver = new ResizeObserver(() => measure())
  // fonts can shift layout after first paint
  void Promise.resolve(document.fonts?.ready).then(() => measure()).catch(() => {})
})

onUnmounted(() => {
  if (onWindowResize) window.removeEventListener('resize', onWindowResize)
  if (resizeObserver) resizeObserver.disconnect()
  cancelAnimationFrame(rafId)
})

// re-measure whenever the graph content changes
watch([layerColumns, () => team.value?.agents.length], () => {
  void nextTick(observeAndMeasure)
})
</script>

<template>
  <div class="mx-auto w-full max-w-[1400px] px-6 py-8 md:px-10 md:py-10">
    <!-- header -->
    <div class="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0 max-w-[980px]">
        <h1 class="at-h2 at-t-xl">{{ t('team.canvas') }}</h1>
        <p class="mt-2 line-clamp-2 at-t-base leading-snug at-muted" :title="store.current?.task || t('exec.running')">
          {{ store.current?.task || t('exec.running') }}
        </p>
        <p class="mt-1.5 font-mono at-t-xs at-dim">
          {{ team?.agents.length ?? 0 }} {{ t('team.agents') }} · {{ allEdges.length }} {{ t('team.edges') }}
        </p>
      </div>
      <p v-if="error" role="alert" class="at-t-base at-danger-text">{{ error }} <span class="at-t-xs at-muted">{{ t('common.error_reload_hint') }}</span></p>
    </div>

    <!-- Formation rail -->
    <section class="mb-8">
      <h2 class="at-eyebrow mb-3">{{ t('team.formation') }}</h2>
      <ol class="flex w-full flex-wrap items-center gap-x-4 gap-y-3">
        <li v-for="(step, i) in formation" :key="step.label" class="flex items-center gap-2.5">
          <span
            class="inline-flex h-5 w-5 items-center justify-center rounded-full border font-mono at-t-xs font-semibold"
            :class="step.done ? 'border-[var(--at-info)] bg-[var(--at-info-soft)] at-info' : 'at-border at-dim'"
            aria-hidden="true"
          >
            {{ step.done ? '✓' : i + 1 }}
          </span>
          <span class="whitespace-nowrap at-t-sm" :class="step.done ? 'at-fg' : 'at-dim'">{{ step.label }}</span>
          <span v-if="i < formation.length - 1" class="hidden h-px w-6 bg-[var(--at-border)] sm:inline-block" aria-hidden="true" />
        </li>
      </ol>
    </section>

    <!-- DAG canvas -->
    <section class="mb-8">
      <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="at-eyebrow">{{ t('team.dag') }}</h2>
        <p v-if="selectedAgent" class="at-t-xs at-dim">
          {{ t('team.highlight_hint', { name: selectedAgent.name }) }}
        </p>
      </div>

      <div v-if="layerColumns.length" class="at-graph overflow-x-auto pb-2">
        <div ref="graphInner" class="at-graph__inner flex min-w-full items-start gap-6">
          <GraphEdgeLayer :width="svgSize.width" :height="svgSize.height" :edges="edgeShapes" />
          <div
            v-for="(layer, idx) in layerColumns"
            :key="layerKey(layer)"
            class="relative z-10 flex min-w-[190px] flex-1 flex-col gap-4"
          >
            <p class="at-mono at-t-xs uppercase tracking-[0.14em] at-dim">{{ t('team.layer') }} {{ idx + 1 }}</p>
            <button
              v-for="agent in agentsInLayer(layer)"
              :key="agent.id"
              :data-agent-id="agent.id"
              type="button"
              class="at-card at-graph__node w-full cursor-pointer px-4 py-3.5 text-left transition-colors"
              :class="selectedAgentId === agent.id ? 'border-[var(--at-info)]' : 'hover:border-[var(--at-border-strong)]'"
              :aria-pressed="selectedAgentId === agent.id"
              @click="selectedAgentId = agent.id"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="truncate at-t-lg font-semibold at-fg">{{ agent.name }}</span>
                <AgentStatus :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
              </div>
              <p class="mt-1.5 truncate font-mono at-t-xs at-dim">{{ (agent.tools || []).join(' · ') || '—' }}</p>
              <p class="mt-2 line-clamp-2 at-t-xs at-muted">{{ (agent.capabilities || []).join(', ') }}</p>
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="!error" class="at-card flex flex-col items-center gap-2 py-16 text-center">
        <UnitIcon name="inbox" :size="22" class="at-dim" />
        <p class="at-t-base at-muted">{{ t('team.waiting') }}</p>
      </div>

      <!-- Accessible text fallback / real dependency list (M1 req. 9) -->
      <div v-if="layerColumns.length" class="mt-4">
        <h3 class="at-eyebrow mb-2">{{ t('team.dependency_list') }}</h3>
        <ul v-if="allEdges.length" class="at-dependency-list">
          <li
            v-for="edge in allEdges"
            :key="`${edge.source}->${edge.target}`"
            class="at-dependency-list__row"
          >
            <button type="button" class="at-link-btn" @click="selectedAgentId = edge.source">
              {{ agentName(edge.source) }}
            </button>
            <span aria-hidden="true" class="at-dim">→</span>
            <button type="button" class="at-link-btn" @click="selectedAgentId = edge.target">
              {{ agentName(edge.target) }}
            </button>
            <span
              v-if="!knownAgentIds.has(edge.source) || !knownAgentIds.has(edge.target)"
              class="at-chip at-chip--warn"
            >{{ t('team.ref_missing') }}</span>
          </li>
        </ul>
        <p v-else class="at-t-xs at-dim">{{ t('team.no_edges') }}</p>
      </div>
    </section>

    <!-- Agent detail -->
    <section>
      <h2 class="at-eyebrow mb-3">{{ t('team.details') }}</h2>
      <div v-if="selectedAgent" class="grid grid-cols-12 gap-6">
        <div class="col-span-12 md:col-span-4">
          <div class="at-card p-5">
            <div class="flex items-center justify-between gap-3">
              <h3 class="at-t-lg font-semibold at-fg">{{ selectedAgent.name }}</h3>
              <AgentStatus
                :status="(store.agentStatuses as Record<string, string>)[selectedAgent.id] || selectedAgent.status"
                :label="true"
              />
            </div>
            <dl class="mt-4 space-y-3 at-t-sm">
              <div>
                <dt class="at-dim">{{ t('exec.capabilities') }}</dt>
                <dd class="mt-1.5 flex flex-wrap gap-1.5">
                  <span v-for="cap in selectedAgent.capabilities" :key="cap" class="at-chip">{{ cap }}</span>
                </dd>
              </div>
              <div>
                <dt class="at-dim">{{ t('exec.tools') }}</dt>
                <dd class="mt-0.5 font-mono at-fg">{{ (selectedAgent.tools || []).join(', ') || '—' }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="at-dim">{{ t('team.layer_label') }}</dt>
                <dd class="at-num at-fg">{{ layerOf(selectedAgent.id) + 1 }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="at-dim">{{ t('team.attempt') }}</dt>
                <dd class="at-num at-fg">#{{ selectedAgent.attempt }}</dd>
              </div>
            </dl>
          </div>
        </div>

        <div v-if="realEdges.length || missingEdges.length" class="col-span-12 md:col-span-4">
          <h3 class="at-eyebrow mb-3">{{ t('team.artifact_flow') }}</h3>
          <ul class="space-y-2 at-t-sm at-muted">
            <li
              v-for="edge in allEdges"
              :key="`flow-${edge.source}->${edge.target}`"
              class="flex flex-wrap items-center gap-x-2 gap-y-1"
              :class="isIncident(edge) ? 'at-fg' : ''"
            >
              <span class="font-medium">{{ agentName(edge.source) }}</span>
              <span class="at-dim" aria-hidden="true">→</span>
              <span>{{ agentName(edge.target) }}</span>
            </li>
          </ul>
        </div>

        <div v-if="team?.explanation" class="col-span-12 md:col-span-4">
          <h3 class="at-eyebrow mb-3">{{ t('team.why') }}</h3>
          <p class="at-t-sm leading-relaxed at-muted">{{ team.explanation.reasoning }}</p>
        </div>
      </div>
      <p v-else class="at-card p-5 at-t-sm at-dim">{{ t('team.select_agent') }}</p>
    </section>
  </div>
</template>
