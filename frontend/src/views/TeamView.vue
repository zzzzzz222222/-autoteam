<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import StatusBadge from '@/components/StatusBadge.vue'
import type { TeamResponse } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const team = ref<TeamResponse | null>(null)
const selectedAgentId = ref<string | null>(null)
const error = ref<string | null>(null)

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

// Simple layer-based DAG layout: each layer = a column.
function layerAgents(layer: string[]): TeamResponse['agents'] {
  return team.value?.agents.filter((a) => layer.includes(a.id)) ?? []
}

const selectedAgent = computed(() =>
  team.value?.agents.find((a) => a.id === selectedAgentId.value) ?? null,
)
</script>

<template>
  <div class="grid grid-cols-12 gap-4">
    <!-- DAG visualization -->
    <section class="col-span-8 rounded-lg border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <span class="text-xs font-semibold uppercase tracking-wide text-zinc-400">Dependency graph</span>
        <span class="text-xs text-zinc-400">{{ team?.agents.length ?? 0 }} agents · {{ team?.edges.length ?? 0 }} edges</span>
      </div>

      <div v-if="error" class="py-10 text-center text-sm text-red-600">{{ error }}</div>

      <!-- Layer columns -->
      <div v-if="team?.layers?.length" class="flex gap-6 overflow-x-auto pb-4">
        <div v-for="(layer, idx) in team.layers" :key="idx" class="flex min-w-[150px] flex-col gap-3">
          <p class="text-center text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Layer {{ idx + 1 }}
          </p>
          <div
            v-for="agent in layerAgents(layer)"
            :key="agent.id"
            class="rounded-lg border px-3 py-2.5 text-sm shadow-sm transition-all"
            :class="[
              selectedAgentId === agent.id ? 'border-zinc-700 ring-1 ring-zinc-700' : 'border-zinc-200',
            ]"
          >
            <button type="button" class="w-full text-left" @click="selectedAgentId = agent.id">
              <div class="flex items-center justify-between gap-2">
                <span class="font-medium text-zinc-800">{{ agent.name }}</span>
                <StatusBadge :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
              </div>
              <p class="mt-1 text-[11px] text-zinc-500">{{ (agent.capabilities || []).join(', ') }}</p>
            </button>
          </div>
        </div>
      </div>
      <p v-else-if="!error" class="py-10 text-center text-sm text-zinc-400">
        Waiting for team formation…
      </p>

      <!-- Edges list as readable flow -->
      <div v-if="team?.edges?.length" class="mt-4 border-t border-zinc-100 pt-3">
        <p class="mb-2 text-xs font-medium text-zinc-500">Artifact flow</p>
        <ul class="space-y-1 text-xs text-zinc-600">
          <li v-for="(edge, i) in team.edges" :key="i" class="flex items-center gap-2">
            <span>{{ team.agents.find((a) => a.id === edge.source)?.name || edge.source }}</span>
            <span class="text-zinc-400">→</span>
            <span>{{ team.agents.find((a) => a.id === edge.target)?.name || edge.target }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- Selected agent detail -->
    <aside class="col-span-4 space-y-4">
      <div v-if="selectedAgent" class="rounded-lg border border-zinc-200 bg-white p-4 text-sm">
        <div class="flex items-center justify-between">
          <p class="font-semibold text-zinc-900">{{ selectedAgent.name }}</p>
          <StatusBadge :status="(store.agentStatuses as Record<string, string>)[selectedAgent.id] || selectedAgent.status" />
        </div>
        <p class="mt-1 text-xs text-zinc-500">{{ selectedAgent.role }}</p>
        <dl class="mt-4 space-y-2 text-xs">
          <div>
            <dt class="text-zinc-400">Capabilities</dt>
            <dd class="mt-0.5 flex flex-wrap gap-1">
              <span v-for="cap in selectedAgent.capabilities" :key="cap" class="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600">
                {{ cap }}
              </span>
            </dd>
          </div>
          <div>
            <dt class="text-zinc-400">Tools</dt>
            <dd class="mt-0.5">{{ (selectedAgent.tools || []).join(', ') || '—' }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-zinc-400">Execution layer</dt>
            <dd>{{ selectedAgent.layer }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-zinc-400">Attempt</dt>
            <dd>{{ selectedAgent.attempt }}</dd>
          </div>
        </dl>
      </div>
      <div v-else class="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-400">
        Select an agent to inspect it.
      </div>

      <div v-if="team?.explanation" class="rounded-lg border border-zinc-200 bg-white p-4 text-sm">
        <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Formation</p>
        <p class="text-xs leading-relaxed text-zinc-600">{{ team.explanation.reasoning }}</p>
        <ul class="mt-2 flex flex-wrap gap-1">
          <li v-for="cap in team.explanation.required_capabilities" :key="cap" class="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600">
            {{ cap }}
          </li>
        </ul>
      </div>
    </aside>
  </div>
</template>