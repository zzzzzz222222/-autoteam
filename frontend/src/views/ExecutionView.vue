<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import StatusBadge from '@/components/StatusBadge.vue'
import type { ArtifactDto, TeamResponse } from '@/types'

const props = defineProps<{ taskId: string }>()
const route = useRoute()
const store = useTeamStore()
const { t } = useI18n()

const team = ref<TeamResponse | null>(null)
const artifacts = ref<ArtifactDto[]>([])
const selectedAgentId = ref<string | null>(null)
const toolError = ref<string | null>(null)

const isOverview = computed(() => route.name === 'execution')

const filteredEvents = computed(() => store.events)
const toolEvents = computed(() => store.events.filter((e) => e.type === 'TOOL_CALLED'))

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function agentName(agentId: string): string {
  return store.current?.agent_names?.[agentId] ?? agentId ?? ''
}

async function refreshDerived() {
  if (!store.current) return
  try {
    const [teamRes, artRes] = await Promise.all([
      api.getTeam(props.taskId),
      api.getArtifacts(props.taskId),
    ])
    team.value = teamRes
    artifacts.value = artRes.artifacts
    if (!selectedAgentId.value && teamRes.agents.length) {
      selectedAgentId.value = teamRes.agents[0].id
    }
  } catch (err) {
    toolError.value = String(err)
  }
}

let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  void store.loadTask(props.taskId).then(() => {
    void refreshDerived()
  })
  store.startStream(props.taskId)
  timer = setInterval(() => void refreshDerived(), 3000)
})

onUnmounted(() => {
  store.stopStream()
  if (timer) clearInterval(timer)
})

onBeforeRouteLeave(() => {
  store.stopStream()
  if (timer) clearInterval(timer)
})

const selectedAgent = computed(() =>
  team.value?.agents.find((a) => a.id === selectedAgentId.value),
)

const downstream = computed(() => {
  if (!selectedAgent.value || !team.value) return []
  return team.value.edges
    .filter((e) => e.source === selectedAgent.value!.id)
    .map((e) => team.value!.agents.find((a) => a.id === e.target))
    .filter(Boolean)
})

const selectedArtifact = computed(() =>
  artifacts.value.find((a) => a.agent_id === selectedAgentId.value),
)

function eventColor(type: string): string {
  switch (type) {
    case 'TASK_STARTED':
    case 'TEAM_FORMED':
      return 'text-zinc-500'
    case 'AGENT_STARTED':
      return 'text-sky-600'
    case 'TOOL_CALLED':
      return 'text-indigo-600'
    case 'ARTIFACT_CREATED':
    case 'AGENT_OUTPUT':
      return 'text-emerald-600'
    case 'AGENT_FAILED':
    case 'AGENT_RETRY':
    case 'AGENT_REPLANNED':
      return 'text-amber-600'
    case 'TASK_COMPLETED':
      return 'text-zinc-700'
    default:
      return 'text-zinc-500'
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-7xl px-6 py-6">
    <!-- Task header -->
    <div class="mb-6">
      <div class="flex items-center justify-between gap-4">
        <h1 class="truncate text-lg font-semibold text-zinc-900">
          {{ store.current?.task || t('exec.running') }}
        </h1>
        <StatusBadge :status="store.current?.status || 'pending'" />
      </div>
      <p v-if="store.current" class="mt-1 text-xs text-zinc-400">
        {{ store.current.run_id }} · {{ t('exec.mode') }} {{ store.current.mode }} · {{ store.current.event_count }} {{ t('exec.events') }}
      </p>
      <p v-if="toolError" class="mt-1 text-sm text-red-600">{{ toolError }}</p>
    </div>

    <!-- Execution overview -->
    <div v-if="isOverview" class="grid grid-cols-12 gap-4">
      <!-- Team sidebar -->
      <aside class="col-span-3 space-y-4">
        <div class="rounded-lg border border-zinc-200 bg-white">
          <div class="border-b border-zinc-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
            {{ t('exec.team') }}
          </div>
          <ul class="divide-y divide-zinc-100">
            <li v-for="agent in team?.agents ?? []" :key="agent.id">
              <button
                type="button"
                class="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-zinc-50"
                :class="{ 'bg-zinc-50': selectedAgentId === agent.id }"
                @click="selectedAgentId = agent.id"
              >
                <span class="font-medium text-zinc-800">{{ agent.name }}</span>
                <StatusBadge :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
              </button>
            </li>
            <li v-if="!team?.agents.length" class="px-3 py-2.5 text-xs text-zinc-400">
              {{ t('exec.team_forming') }}
            </li>
          </ul>
        </div>

        <!-- Selected agent details -->
        <div v-if="selectedAgent" class="rounded-lg border border-zinc-200 bg-white p-3 text-sm">
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-400">{{ t('exec.agent_details') }}</p>
          <p class="mt-2 font-medium text-zinc-900">{{ selectedAgent.name }}</p>
          <dl class="mt-2 space-y-1.5 text-xs text-zinc-600">
            <div class="flex justify-between gap-2">
              <dt class="text-zinc-400">{{ t('exec.capabilities') }}</dt>
              <dd class="text-right">{{ (selectedAgent.capabilities || []).join(', ') || '—' }}</dd>
            </div>
            <div class="flex justify-between gap-2">
              <dt class="text-zinc-400">{{ t('exec.tools') }}</dt>
              <dd class="text-right">{{ (selectedAgent.tools || []).join(', ') || '—' }}</dd>
            </div>
            <div class="flex justify-between gap-2">
              <dt class="text-zinc-400">{{ t('exec.layer') }}</dt>
              <dd>{{ selectedAgent.layer }}</dd>
            </div>
            <div v-if="downstream.length" class="flex justify-between gap-2">
              <dt class="text-zinc-400">{{ t('exec.feeds') }}</dt>
              <dd class="text-right">{{ downstream.map((a) => a!.name).join(', ') }}</dd>
            </div>
          </dl>
          <div v-if="selectedArtifact" class="mt-3 border-t border-zinc-100 pt-2 text-xs">
            <p class="mb-1 font-medium text-zinc-600">{{ t('exec.artifact') }}</p>
            <p class="text-zinc-500">{{ selectedArtifact.title || selectedArtifact.artifact_id }}</p>
            <p class="text-zinc-400">
              {{ t('exec.artifact_src') }} {{ selectedArtifact.source_records.length }} · {{ t('exec.artifact_ev') }} {{ selectedArtifact.evidence.length }}
            </p>
          </div>
        </div>
      </aside>

      <!-- Execution timeline -->
      <section class="col-span-6 rounded-lg border border-zinc-200 bg-white">
        <div class="flex items-center justify-between border-b border-zinc-100 px-3 py-2">
          <span class="text-xs font-semibold uppercase tracking-wide text-zinc-400">{{ t('exec.timeline') }}</span>
          <span class="text-xs text-zinc-400">
            {{ filteredEvents.length }} {{ t('exec.events') }}
          </span>
        </div>
        <div class="h-[560px] overflow-y-auto px-3 py-2">
          <ol v-if="filteredEvents.length" class="space-y-1.5">
            <li v-for="event in filteredEvents" :key="event.event_id" class="flex gap-3 text-sm">
              <span class="shrink-0 font-mono text-xs text-zinc-400">
                {{ formatTime(event.timestamp) }}
              </span>
              <span class="font-mono text-xs font-medium" :class="eventColor(event.type)">
                {{ event.type }}
              </span>
              <span class="min-w-0 flex-1 truncate text-zinc-600">
                <template v-if="event.agent_id">{{ agentName(event.agent_id) }} — </template>{{ event.message }}
                <template v-if="event.type === 'TOOL_CALLED' && event.metadata.offline">
                  <span class="ml-1 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">{{ t('exec.offline') }}</span>
                </template>
              </span>
            </li>
          </ol>
          <p v-else class="py-8 text-center text-sm text-zinc-400">{{ t('exec.waiting') }}</p>
        </div>
      </section>

      <!-- Right rail: tool calls + provenance counters -->
      <aside class="col-span-3 space-y-4">
        <div class="rounded-lg border border-zinc-200 bg-white">
          <div class="border-b border-zinc-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
            {{ t('exec.tool_calls') }}
          </div>
          <ul class="divide-y divide-zinc-100 px-3 py-1 text-xs">
            <li v-for="event in toolEvents.slice().reverse()" :key="event.event_id" class="flex items-center justify-between gap-2 py-2">
              <span class="font-mono text-zinc-700">{{ (event.metadata.tool || 'tool') }}</span>
              <span v-if="event.metadata.offline" class="rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">{{ t('exec.offline') }}</span>
              <span v-else class="rounded bg-emerald-50 px-1 py-0.5 text-[10px] text-emerald-600">{{ t('exec.web') }}</span>
            </li>
            <li v-if="!toolEvents.length" class="py-2 text-zinc-400">{{ t('exec.no_tool_calls') }}</li>
          </ul>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg border border-zinc-200 bg-white p-3">
            <p class="text-2xl font-semibold text-zinc-900">{{ store.evidenceCount }}</p>
            <p class="text-xs text-zinc-500">{{ t('exec.evidence') }}</p>
          </div>
          <div class="rounded-lg border border-zinc-200 bg-white p-3">
            <p class="text-2xl font-semibold text-zinc-900">{{ store.sourceCount }}</p>
            <p class="text-xs text-zinc-500">{{ t('exec.sources') }}</p>
          </div>
        </div>
      </aside>
    </div>

    <!-- Child route (team / artifacts / result) -->
    <RouterView v-if="!isOverview" v-slot="{ Component }">
      <component :is="Component" :task-id="props.taskId" />
    </RouterView>
  </div>
</template>