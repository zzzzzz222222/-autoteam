<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import AgentStatus from '@/components/AgentStatus.vue'
import type { ExecutionEvent, TeamAgent } from '@/types'

const props = defineProps<{ taskId: string }>()
const route = useRoute()
const store = useTeamStore()
const { t } = useI18n()

const team = ref<TeamAgent[]>([])
const error = ref<string | null>(null)
const selectedAgentId = ref<string | null>(null)

const isOverview = computed(() => route.name === 'execution')

// ---- derived from store (all SSE/API driven, nothing fabricated) -------
const snapshot = computed(() => store.current)

const summary = computed(() => {
  const snap = snapshot.value
  return {
    agents: snap?.agent_names ? Object.keys(snap.agent_names).length : team.value.length,
    layers: snap?.layers?.length ?? 0,
    sources: snap?.final_artifact?.sources.length ?? 0,
    evidence: snap?.final_artifact?.evidence.length ?? 0,
    status: snap?.status ?? 'idle',
    mode: snap?.mode ?? 'offline',
    runId: snap?.run_id ?? '',
  }
})

// latest event type per agent -> drives the "doing" verb (from real events)
function agentDoing(agentId: string): string {
  const last = [...store.events].reverse().find((e) => e.agent_id === agentId)
  if (!last) return ''
  const map: Record<string, string> = {
    AGENT_STARTED: t('act.started'),
    TOOL_CALLED: t(last.metadata.offline ? 'act.tool_offline' : 'act.tool_web'),
    AGENT_OUTPUT: t('act.output'),
    ARTIFACT_CREATED: t('act.artifact'),
    AGENT_FAILED: t('act.failed'),
    AGENT_RETRY: t('act.retrying'),
    AGENT_REPLANNED: t('act.replanned'),
  }
  return map[last.type] ?? ''
}

const groupedEvents = computed(() => {
  const groups: Record<string, ExecutionEvent[]> = {}
  for (const event of store.events) {
    if (!event.agent_id) continue
    if (!groups[event.agent_id]) groups[event.agent_id] = []
    groups[event.agent_id].push(event)
  }
  return groups
})

const orderedAgents = computed(() => {
  const agents = team.value.length ? team.value : snapshotAgents.value
  return agents
})

const snapshotAgents = computed<TeamAgent[]>(() => {
  const snap = snapshot.value
  if (!snap) return []
  return Object.entries(snap.agent_names).map(([id, name]) => ({
    id,
    name,
    role: '',
    capabilities: [],
    tools: [],
    layer: 0,
    status: snap.agent_results[id]?.status ?? 'pending',
    attempt: snap.agent_results[id]?.attempt ?? 1,
  }))
})

async function loadTeam() {
  try {
    const res = await api.getTeam(props.taskId)
    team.value = res.agents
    if (!selectedAgentId.value && res.agents.length) {
      selectedAgentId.value = res.agents[0].id
    }
  } catch (err) {
    error.value = String(err)
  }
}

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function eventGlyph(type: string): string {
  switch (type) {
    case 'TOOL_CALLED':
      return 'tool'
    case 'ARTIFACT_CREATED':
    case 'AGENT_OUTPUT':
      return 'artifact'
    case 'AGENT_RETRY':
    case 'AGENT_FAILED':
    case 'AGENT_REPLANNED':
      return 'retry'
    default:
      return 'event'
  }
}

function glyphColor(kind: string): string {
  switch (kind) {
    case 'tool':
      return 'text-blue-600'
    case 'artifact':
      return 'text-emerald-600'
    case 'retry':
      return 'text-amber-600'
    default:
      return 'text-zinc-400'
  }
}

function glyphLabel(event: ExecutionEvent): string {
  switch (event.type) {
    case 'TOOL_CALLED':
      return event.metadata.offline ? t('act.tool_offline') : t('act.tool_web')
    case 'ARTIFACT_CREATED':
      return t('act.artifact')
    case 'AGENT_OUTPUT':
      return t('act.output')
    case 'AGENT_STARTED':
      return t('act.started')
    case 'AGENT_RETRY':
      return t('act.retrying')
    case 'AGENT_FAILED':
      return t('act.failed')
    case 'AGENT_REPLANNED':
      return t('act.replanned')
    default:
      return event.type.toLowerCase()
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  void store.loadTask(props.taskId).then(() => {
    void loadTeam()
  })
  store.startStream(props.taskId)
  pollTimer = setInterval(() => {
    if (snapshot.value?.status === 'running') void loadTeam()
  }, 4000)
})

onUnmounted(cleanup)
onBeforeRouteLeave(cleanup)

function cleanup() {
  store.stopStream()
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-8 py-8">
    <!-- Run header (contextual bar, not a card) -->
    <div class="mb-8 flex items-end justify-between gap-6">
      <div class="min-w-0">
        <p class="tok-eyebrow mb-1.5">{{ t('exec.run') }}</p>
        <h1 class="truncate text-xl font-semibold tracking-tight text-zinc-900">
          {{ snapshot?.task || t('exec.running') }}
        </h1>
        <p class="mt-1 font-mono text-[11px] text-zinc-400">{{ summary.runId }}</p>
      </div>
      <div class="hidden shrink-0 gap-8 text-right sm:flex">
        <div>
          <p class="font-mono text-lg font-medium text-zinc-900">{{ summary.agents }}</p>
          <p class="text-[11px] text-zinc-400">{{ t('exec.agents_count') }}</p>
        </div>
        <div>
          <p class="font-mono text-lg font-medium text-zinc-900">{{ summary.layers }}</p>
          <p class="text-[11px] text-zinc-400">{{ t('exec.layers_count') }}</p>
        </div>
        <div>
          <p class="font-mono text-lg font-medium text-zinc-900">{{ summary.sources }}</p>
          <p class="text-[11px] text-zinc-400">{{ t('exec.sources') }}</p>
        </div>
      </div>
    </div>

    <!-- Overview: Live Team Activity -->
    <div v-if="isOverview" class="grid grid-cols-12 gap-10">
      <!-- Agent column (activity stream per agent) -->
      <div class="col-span-8 space-y-7">
        <p class="tok-eyebrow">{{ t('exec.team_activity') }}</p>

        <div v-if="error" class="text-sm text-red-600">{{ error }}</div>

        <div
          v-for="agent in orderedAgents"
          :key="agent.id"
          class="at-fade-in border-b border-zinc-200 pb-6"
        >
          <div class="flex items-baseline gap-3">
            <AgentStatus :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
            <span class="text-[14px] font-semibold text-zinc-900">{{ agent.name }}</span>
            <span class="text-[12px] text-zinc-400">
              {{ agentDoing(agent.id) || '·' }}
            </span>
          </div>

          <div v-if="(groupedEvents[agent.id] ?? []).length" class="mt-2.5 space-y-1.5">
            <div
              v-for="event in groupedEvents[agent.id]"
              :key="event.event_id"
              class="flex items-center gap-3 text-[13px]"
            >
              <span class="w-16 shrink-0 font-mono text-[11px] text-zinc-400">
                {{ formatTime(event.timestamp) }}
              </span>
              <span
                class="w-16 shrink-0 text-[11px] font-medium"
                :class="glyphColor(eventGlyph(event.type))"
              >
                {{ glyphLabel(event) }}
              </span>
              <span class="min-w-0 truncate text-zinc-600">{{ event.message }}</span>
            </div>
          </div>
          <p v-else class="mt-1.5 text-[12px] text-zinc-300">{{ t('exec.no_activity') }}</p>
        </div>

        <p v-if="!orderedAgents.length" class="py-12 text-center text-sm text-zinc-400">
          {{ t('exec.waiting') }}
        </p>
      </div>

      <!-- Right rail: provenance + mode truth -->
      <aside class="col-span-4 space-y-8">
        <div>
          <p class="tok-eyebrow mb-2.5">{{ t('exec.tool_calls') }}</p>
          <ul class="space-y-1.5">
            <li
              v-for="event in store.events.filter((e) => e.type === 'TOOL_CALLED').reverse().slice(0, 8)"
              :key="event.event_id"
              class="flex items-center justify-between text-[13px]"
            >
              <span class="font-mono text-zinc-700">{{ event.metadata.tool || 'tool' }}</span>
              <span
                class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                :class="event.metadata.offline ? 'bg-zinc-100 text-zinc-500' : 'bg-emerald-50 text-emerald-700'"
              >
                {{ event.metadata.offline ? 'offline' : 'web' }}
              </span>
            </li>
            <li v-if="!store.events.some((e) => e.type === 'TOOL_CALLED')" class="text-[12px] text-zinc-300">
              {{ t('exec.no_tool_calls') }}
            </li>
          </ul>
        </div>

        <div>
          <p class="tok-eyebrow mb-2.5">{{ t('exec.provenance') }}</p>
          <div class="flex gap-8">
            <div>
              <p class="font-mono text-lg font-medium text-zinc-900">{{ summary.evidence }}</p>
              <p class="text-[11px] text-zinc-400">{{ t('exec.evidence') }}</p>
            </div>
            <div>
              <p class="font-mono text-lg font-medium text-zinc-900">{{ summary.sources }}</p>
              <p class="text-[11px] text-zinc-400">{{ t('exec.sources') }}</p>
            </div>
          </div>
          <p class="mt-3 text-[11px] text-zinc-400">
            {{ t('exec.mode_truth') }}
          </p>
        </div>
      </aside>
    </div>

    <!-- Child phase (team / artifacts / result) -->
    <RouterView v-else v-slot="{ Component }">
      <component :is="Component" :task-id="props.taskId" />
    </RouterView>
  </div>
</template>