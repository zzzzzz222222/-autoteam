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

/** Strip the redundant owner prefix — the agent name is already the section header. */
function eventMessage(event: ExecutionEvent, agent: TeamAgent): string {
  const raw = event.message ?? ''
  const name = agent.name
  const lower = raw.startsWith(name) ? raw.slice(name.length) : raw
  return lower.trim().replace(/^[：:\s]+/, '') || raw
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
  <div class="mx-auto w-full max-w-[1400px] px-10 py-10">
    <!-- Run header: wide context bar with metrics -->
    <div class="mb-10 flex flex-wrap items-end justify-between gap-6">
      <div class="min-w-0 max-w-[720px]">
        <p class="tok-eyebrow mb-2">{{ t('exec.run') }}</p>
        <h1 class="tok-page-title truncate" :title="snapshot?.task || t('exec.running')">{{ snapshot?.task || t('exec.running') }}</h1>
        <p class="mt-2 font-mono text-[13px] text-zinc-400">{{ summary.runId }}</p>
      </div>
      <div class="flex shrink-0 gap-10">
        <div>
          <p class="tok-metric">{{ summary.agents }}</p>
          <p class="text-[13px] text-zinc-400">{{ t('exec.agents_count') }}</p>
        </div>
        <div>
          <p class="tok-metric">{{ summary.layers }}</p>
          <p class="text-[13px] text-zinc-400">{{ t('exec.layers_count') }}</p>
        </div>
        <div>
          <p class="tok-metric">{{ summary.sources }}</p>
          <p class="text-[13px] text-zinc-400">{{ t('exec.sources') }}</p>
        </div>
        <div>
          <p class="tok-metric">{{ summary.evidence }}</p>
          <p class="text-[13px] text-zinc-400">{{ t('exec.evidence') }}</p>
        </div>
      </div>
    </div>

    <!-- Overview: Live Team Activity (wide) -->
    <div v-if="isOverview" class="grid grid-cols-12 gap-12">
      <!-- Activity stream -->
      <div class="col-span-8 space-y-8">
        <p class="tok-eyebrow">{{ t('exec.team_activity') }}</p>

        <div v-if="error" class="text-[15px] text-red-600">{{ error }}</div>

        <div
          v-for="agent in orderedAgents"
          :key="agent.id"
          class="at-fade-in at-card p-5"
        >
          <div class="flex items-center gap-3">
            <AgentStatus :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
            <span class="text-[17px] font-semibold text-zinc-900">{{ agent.name }}</span>
            <span class="text-[15px] text-zinc-500">{{ agentDoing(agent.id) || '·' }}</span>
          </div>

          <div v-if="(groupedEvents[agent.id] ?? []).length" class="mt-3 space-y-1.5">
            <div
              v-for="event in groupedEvents[agent.id]"
              :key="event.event_id"
              class="flex items-center gap-4 text-[15px]"
            >
              <span class="w-20 shrink-0 font-mono text-[13px] text-zinc-400">
                {{ formatTime(event.timestamp) }}
              </span>
              <span
                class="w-20 shrink-0 text-[13px] font-medium"
                :class="glyphColor(eventGlyph(event.type))"
              >
                {{ glyphLabel(event) }}
              </span>
              <span class="min-w-0 flex-1 truncate text-zinc-600" :title="event.message">
                {{ eventMessage(event, agent) }}
              </span>
            </div>
          </div>
          <p v-else class="mt-2 text-[14px] text-zinc-400">{{ t('exec.no_activity') }}</p>
        </div>

        <p v-if="!orderedAgents.length" class="py-12 text-center text-[15px] text-zinc-400">
          {{ t('exec.waiting') }}
        </p>
      </div>

      <!-- Right rail: provenance + mode truth -->
      <aside class="col-span-4 space-y-10">
        <div>
          <p class="tok-eyebrow mb-3">{{ t('exec.tool_calls') }}</p>
          <ul class="space-y-2">
            <li
              v-for="event in store.events.filter((e) => e.type === 'TOOL_CALLED').reverse().slice(0, 8)"
              :key="event.event_id"
              class="flex min-w-0 items-center justify-between gap-2 text-[15px]"
            >
              <span class="truncate font-mono text-zinc-700" :title="event.metadata.tool || 'tool'">{{ event.metadata.tool || 'tool' }}</span>
              <span
                class="rounded-full px-2.5 py-0.5 text-[12px] font-medium"
                :class="event.metadata.offline ? 'bg-zinc-100 text-zinc-500' : 'bg-emerald-50 text-emerald-700'"
              >
                {{ event.metadata.offline ? 'offline' : 'web' }}
              </span>
            </li>
            <li v-if="!store.events.some((e) => e.type === 'TOOL_CALLED')" class="text-[14px] text-zinc-400">
              {{ t('exec.no_tool_calls') }}
            </li>
          </ul>
        </div>

        <div>
          <p class="tok-eyebrow mb-3">{{ t('exec.provenance') }}</p>
          <div class="flex gap-10">
            <div>
              <p class="tok-metric">{{ summary.evidence }}</p>
              <p class="text-[13px] text-zinc-400">{{ t('exec.evidence') }}</p>
            </div>
            <div>
              <p class="tok-metric">{{ summary.sources }}</p>
              <p class="text-[13px] text-zinc-400">{{ t('exec.sources') }}</p>
            </div>
          </div>
          <p class="mt-3 text-[13px] text-zinc-400">
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