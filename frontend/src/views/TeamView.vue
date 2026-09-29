<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import AgentStatus from '@/components/AgentStatus.vue'
import type { TeamResponse } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const team = ref<TeamResponse | null>(null)
const selectedAgentId = ref<string | null>(null)
const error = ref<string | null>(null)

// dynamic-formation narrative (labels are presentation-only; the underlying
// data comes from the real ExecutionPlan via GET /team + ExecutionTrace)
const formation = computed(() => [
  { label: t('tf.task_understanding'), done: true },
  { label: t('tf.capability_discovery'), done: !!team.value?.explanation },
  { label: t('tf.role_allocation'), done: team.value != null },
  { label: t('tf.agent_factory'), done: team.value != null },
  { label: t('tf.dag_validation'), done: (team.value?.edges?.length ?? 0) >= 0 && team.value != null },
  { label: t('tf.execution'), done: executionReached.value },
])

// "execution reached" = the run started; derived from the snapshot, and boolean
// so a direct deep-link to /team (before the store loads) never shows a mixed
// state rail (all-blue checks + one grey step).
const executionReached = computed(
  () =>
    store.current != null &&
    (store.current.started_at != null ||
      store.current.status === 'running' ||
      store.current.status === 'success'),
)

async function load() {
  try {
    team.value = await api.getTeam(props.taskId)
    if (!selectedAgentId.value && team.value.agents.length) {
      selectedAgentId.value = team.value.agents[0].id
    }
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)

const selectedAgent = computed(() =>
  team.value?.agents.find((a) => a.id === selectedAgentId.value) ?? null,
)

const layerColumns = computed(() => team.value?.layers ?? [])

function agentsInLayer(layer: string[]) {
  return team.value?.agents.filter((a) => layer.includes(a.id)) ?? []
}

function layerOf(agentId: string): number {
  const layers = team.value?.layers ?? []
  for (let i = 0; i < layers.length; i++) if (layers[i].includes(agentId)) return i
  return 0
}

const flows = computed(() => {
  const out: Record<string, string[]> = {}
  for (const edge of team.value?.edges ?? []) {
    if (!out[edge.source]) out[edge.source] = []
    out[edge.source].push(edge.target)
  }
  return out
})

function agentName(id: string): string {
  return team.value?.agents.find((a) => a.id === id)?.name ?? id
}
</script>

<template>
  <div class="mx-auto w-full max-w-[1400px] px-10 py-10">
    <!-- header -->
    <div class="mb-8 flex items-end justify-between gap-6">
      <div>
        <p class="tok-eyebrow mb-2">{{ t('team.canvas') }}</p>
        <h1 class="tok-page-title" :title="store.current?.task || t('exec.running')">{{ store.current?.task || t('exec.running') }}</h1>
        <p class="mt-2 text-[14px] text-zinc-400">
          {{ team?.agents.length ?? 0 }} {{ t('team.agents') }} · {{ team?.edges.length ?? 0 }} {{ t('team.edges') }}
        </p>
      </div>
      <p v-if="error" class="text-[15px] text-red-600">{{ error }}</p>
    </div>

    <div class="grid grid-cols-12 gap-10">
      <!-- Formation rail (top, horizontal on wide screens) -->
      <div class="col-span-12">
        <div class="flex w-full items-center gap-0 border-b border-zinc-200 pb-6">
          <template v-for="(step, i) in formation" :key="step.label">
            <div class="flex items-center gap-3 pr-5">
              <span
                class="inline-flex h-5 w-5 items-center justify-center rounded-full border-2 text-[11px] font-semibold"
                :class="step.done ? 'border-blue-600 bg-blue-600 text-white' : 'border-zinc-300 text-zinc-400'"
              >
                {{ step.done ? '✓' : i + 1 }}
              </span>
              <span
                class="whitespace-nowrap text-[14px] font-medium"
                :class="step.done ? 'text-zinc-800' : 'text-zinc-400'"
              >
                {{ step.label }}
              </span>
            </div>
            <div v-if="i < formation.length - 1" class="h-px min-w-8 flex-1 bg-zinc-200" />
          </template>
        </div>
      </div>

      <!-- Team canvas: large DAG (columns tolerate overflow via horizontal scroll) -->
      <div class="col-span-9 min-w-0">
        <div v-if="layerColumns.length" class="flex items-start gap-8 overflow-x-auto pb-2">
          <div v-for="(layer, idx) in layerColumns" :key="idx" class="flex min-w-[180px] flex-1 flex-col gap-5">
            <p class="font-mono text-[13px] uppercase tracking-widest text-zinc-300">
              {{ t('team.layer') }} {{ idx + 1 }}
            </p>
            <div
              v-for="agent in agentsInLayer(layer)"
              :key="agent.id"
              class="at-card group min-h-[104px] cursor-pointer px-5 py-4 transition-colors"
              :class="[
                selectedAgentId === agent.id
                  ? 'border-blue-600 ring-2 ring-blue-600/15'
                  : 'hover:border-zinc-400',
              ]"
              @click="selectedAgentId = agent.id"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="text-[17px] font-semibold text-zinc-900">{{ agent.name }}</span>
                <AgentStatus
                  :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status"
                />
              </div>
              <p class="mt-1 text-[13px] text-zinc-400">{{ (agent.tools || []).join(' · ') || '—' }}</p>
              <p class="mt-2 text-[13px] text-zinc-500">
                {{ (agent.capabilities || []).join(', ') }}
              </p>
            </div>
          </div>
        </div>
        <p v-else-if="!error" class="py-16 text-center text-[15px] text-zinc-400">
          {{ t('team.waiting') }}
        </p>
      </div>

      <!-- agent detail -->
      <aside class="col-span-3">
        <div class="sticky top-6">
          <p class="tok-eyebrow mb-3">{{ t('team.details') }}</p>
          <div v-if="selectedAgent" class="at-card p-5">
            <div class="flex items-center justify-between">
              <h3 class="text-[18px] font-semibold text-zinc-900">{{ selectedAgent.name }}</h3>
              <AgentStatus
                :status="(store.agentStatuses as Record<string, string>)[selectedAgent.id] || selectedAgent.status"
                :label="true"
              />
            </div>
            <dl class="mt-4 space-y-3 text-[14px]">
              <div>
                <dt class="text-zinc-400">{{ t('exec.capabilities') }}</dt>
                <dd class="mt-1 flex flex-wrap gap-1.5">
                  <span
                    v-for="cap in selectedAgent.capabilities"
                    :key="cap"
                    class="rounded-full bg-zinc-100 px-2.5 py-1 text-[13px] text-zinc-700"
                  >
                    {{ cap }}
                  </span>
                </dd>
              </div>
              <div>
                <dt class="text-zinc-400">{{ t('exec.tools') }}</dt>
                <dd class="mt-0.5 font-mono text-[14px] text-zinc-700">
                  {{ (selectedAgent.tools || []).join(', ') || '—' }}
                </dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-zinc-400">{{ t('team.layer_label') }}</dt>
                <dd>{{ layerOf(selectedAgent.id) + 1 }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-zinc-400">{{ t('team.attempt') }}</dt>
                <dd>#{{ selectedAgent.attempt }}</dd>
              </div>
            </dl>
          </div>
          <p v-else class="at-card p-5 text-[14px] text-zinc-400">{{ t('team.select_agent') }}</p>

          <div v-if="Object.keys(flows).length" class="mt-6">
            <p class="tok-eyebrow mb-3">{{ t('team.artifact_flow') }}</p>
            <ul class="space-y-2 text-[14px] text-zinc-600">
              <li v-for="(targets, source) in flows" :key="source" class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="font-medium text-zinc-800">{{ agentName(source) }}</span>
                <span class="text-zinc-400">→</span>
                <span>{{ targets.map((tg) => agentName(tg)).join(', ') }}</span>
              </li>
            </ul>
          </div>

          <div v-if="team?.explanation" class="mt-6 border-t border-zinc-200 pt-4">
            <p class="tok-eyebrow mb-2">{{ t('team.why') }}</p>
            <p class="text-[14px] leading-relaxed text-zinc-500">{{ team.explanation.reasoning }}</p>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>