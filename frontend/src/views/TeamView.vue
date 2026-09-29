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

// The dynamic-formation narrative (mapped to the real pipeline; labels are
// presentation-only, the underlying data comes from ExecutionPlan.explanation)
const formation = computed(() => [
  { label: t('tf.task_understanding'), done: true },
  { label: t('tf.capability_discovery'), done: !!team.value?.explanation },
  { label: t('tf.role_allocation'), done: team.value != null },
  { label: t('tf.agent_factory'), done: team.value != null },
  { label: t('tf.dag_validation'), done: (team.value?.edges?.length ?? 0) >= 0 && team.value != null },
  { label: t('tf.execution'), done: store.current?.status !== 'running' && store.current != null },
])

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

// layer-based columns for the canvas: left column = earlier layers
const layerColumns = computed(() => team.value?.layers ?? [])

function agentsInLayer(layer: string[]) {
  return team.value?.agents.filter((a) => layer.includes(a.id)) ?? []
}

function layerOf(agentId: string): number {
  const layers = team.value?.layers ?? []
  for (let i = 0; i < layers.length; i++) if (layers[i].includes(agentId)) return i
  return 0
}

// edges grouped for drawing: source -> targets (only cross-layer edges drawn as flow)
const flows = computed(() => {
  const out: Record<string, string[]> = {}
  for (const edge of team.value?.edges ?? []) {
    if (!out[edge.source]) out[edge.source] = []
    out[edge.source].push(edge.target)
  }
  return out
})
</script>

<template>
  <div class="grid grid-cols-12 gap-10">
    <!-- Formation rail (left, very restrained) -->
    <div class="col-span-2">
      <p class="tok-eyebrow mb-4">{{ t('team.formation') }}</p>
      <ol class="space-y-0">
        <li
          v-for="(step, i) in formation"
          :key="step.label"
          class="relative flex items-start gap-2.5 pb-5"
        >
          <span
            v-if="i < formation.length - 1"
            class="absolute left-[5px] top-4 h-full w-px bg-zinc-200"
          />
          <span
            class="relative z-10 mt-0.5 inline-block h-[11px] w-[11px] rounded-full border-2"
            :class="step.done ? 'border-zinc-900 bg-zinc-900' : 'border-zinc-300 bg-white'"
          />
          <span
            class="text-[12px] leading-tight"
            :class="step.done ? 'text-zinc-700' : 'text-zinc-400'"
          >
            {{ step.label }}
          </span>
        </li>
      </ol>
    </div>

    <!-- Team canvas (DAG) -->
    <div class="col-span-7">
      <div class="mb-4 flex items-center justify-between">
        <p class="tok-eyebrow">{{ t('team.canvas') }}</p>
        <span class="text-[11px] text-zinc-400">
          {{ team?.agents.length ?? 0 }} agents · {{ team?.edges.length ?? 0 }} flows
        </span>
      </div>

      <div v-if="error" class="text-sm text-red-600">{{ error }}</div>

      <!-- layer columns -->
      <div v-if="layerColumns.length" class="flex gap-8">
        <div v-for="(layer, idx) in layerColumns" :key="idx" class="flex flex-col gap-4">
          <p class="font-mono text-[10px] uppercase tracking-widest text-zinc-300">
            L{{ idx + 1 }}
          </p>
          <div
            v-for="agent in agentsInLayer(layer)"
            :key="agent.id"
            class="group cursor-pointer rounded-lg border px-3.5 py-3 transition-colors"
            :class="[
              selectedAgentId === agent.id
                ? 'border-zinc-900 bg-zinc-900 text-white'
                : 'border-zinc-200 bg-white hover:border-zinc-400',
            ]"
            @click="selectedAgentId = agent.id"
          >
            <div class="flex items-center justify-between gap-3">
              <span class="text-[13px] font-semibold">{{ agent.name }}</span>
              <span :class="selectedAgentId === agent.id ? 'text-white' : ''">
                <AgentStatus :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
              </span>
            </div>
            <p class="mt-1 text-[11px]" :class="selectedAgentId === agent.id ? 'text-zinc-300' : 'text-zinc-400'">
              {{ (agent.tools || []).join(' · ') }}
            </p>
            <div class="mt-1.5 flex items-center gap-3 text-[10px]" :class="selectedAgentId === agent.id ? 'text-zinc-300' : 'text-zinc-400'">
              <span>{{ agent.capabilities?.length }} {{ t('team.capabilities') }}</span>
            </div>
          </div>
        </div>
      </div>
      <p v-else-if="!error" class="py-12 text-center text-sm text-zinc-400">
        {{ t('team.waiting') }}
      </p>

      <!-- flow list -->
      <div v-if="Object.keys(flows).length" class="mt-6 border-t border-zinc-200 pt-4">
        <p class="tok-eyebrow mb-2.5">{{ t('team.artifact_flow') }}</p>
        <ul class="space-y-1 text-[12px] text-zinc-600">
          <li v-for="(targets, source) in flows" :key="source">
            <span class="font-medium text-zinc-700">
              {{ team?.agents.find((a) => a.id === source)?.name || source }}
            </span>
            <span class="mx-1.5 text-zinc-400">→</span>
            {{ targets.map((t) => team?.agents.find((a) => a.id === t)?.name || t).join(', ') }}
          </li>
        </ul>
      </div>
    </div>

    <!-- Agent detail -->
    <aside class="col-span-3">
      <p class="tok-eyebrow mb-4">{{ t('team.details') }}</p>
      <div v-if="selectedAgent" class="sticky top-6">
        <div class="flex items-baseline justify-between">
          <h3 class="text-[15px] font-semibold text-zinc-900">{{ selectedAgent.name }}</h3>
          <AgentStatus :status="(store.agentStatuses as Record<string, string>)[selectedAgent.id] || selectedAgent.status" :label="true" />
        </div>
        <dl class="mt-4 space-y-3 text-[13px]">
          <div>
            <dt class="text-zinc-400">{{ t('exec.capabilities') }}</dt>
            <dd class="mt-0.5 flex flex-wrap gap-1.5">
              <span
                v-for="cap in selectedAgent.capabilities"
                :key="cap"
                class="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-700"
              >
                {{ cap }}
              </span>
            </dd>
          </div>
          <div>
            <dt class="text-zinc-400">{{ t('exec.tools') }}</dt>
            <dd class="mt-0.5 font-mono text-[12px] text-zinc-700">
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
      <p v-else class="text-[13px] text-zinc-400">{{ t('team.select_agent') }}</p>

      <div v-if="team?.explanation" class="mt-8 border-t border-zinc-200 pt-4">
        <p class="tok-eyebrow mb-2">{{ t('team.why') }}</p>
        <p class="text-[12px] leading-relaxed text-zinc-500">{{ team.explanation.reasoning }}</p>
      </div>
    </aside>
  </div>
</template>