<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import AgentStatus from '@/components/AgentStatus.vue'
import UnitIcon from '@/components/UnitIcon.vue'
import type { ExecutionEvent, TeamAgent } from '@/types'

const props = defineProps<{ taskId: string }>()
const route = useRoute()
const store = useTeamStore()
const { t } = useI18n()

const team = ref<TeamAgent[]>([])
const error = ref<string | null>(null)

const isOverview = computed(() => route.name === 'execution')
const snapshot = computed(() => store.current)
const events = computed(() => store.events)

const summary = computed(() => {
  const snap = snapshot.value
  return {
    agents: snap?.agent_names ? Object.keys(snap.agent_names).length : team.value.length,
    layers: snap?.layers?.length ?? 0,
    sources: snap?.final_artifact?.sources.length ?? 0,
    evidence: snap?.final_artifact?.evidence.length ?? 0,
    status: snap?.status ?? 'idle',
    runId: snap?.run_id ?? '',
  }
})

// --- tool kind comes from the real execution event (Phase 1 transparency) ---
function toolKindKey(meta: Record<string, unknown> | undefined): string {
  const kind = String(meta?.tool_kind || (meta?.offline ? 'offline_mock' : 'web'))
  switch (kind) {
    case 'web':
      return 'tool.web'
    case 'local':
      return 'tool.local'
    case 'offline_fallback':
      return 'tool.fallback'
    default:
      return 'tool.mock'
  }
}
// M6: tool kind is shown as a low-saturation dot beside its text label,
// never as a full high-saturation chip and never as a success/failure signal.
function toolKindDot(meta: Record<string, unknown> | undefined): string {
  const kind = String(meta?.tool_kind || (meta?.offline ? 'offline_mock' : 'web'))
  switch (kind) {
    case 'web':
      return 'at-dot--web'
    case 'local':
      return 'at-dot--local'
    case 'offline_fallback':
      return 'at-dot--fallback'
    default:
      return 'at-dot--mock'
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

function agentDoing(agentId: string): string {
  const finalStatus = snapshot.value?.agent_results?.[agentId]?.status
  if (finalStatus === 'success') return t('act.done')
  if (finalStatus === 'failed') return t('act.failed')
  const last = [...store.events].reverse().find((e) => e.agent_id === agentId)
  if (!last) return finalStatus ?? ''
  const map: Record<string, string> = {
    AGENT_STARTED: t('act.started'),
    TOOL_CALLED: t(toolKindKey(last.metadata)),
    AGENT_OUTPUT: t('act.output'),
    ARTIFACT_CREATED: t('act.artifact'),
    AGENT_FAILED: t('act.failed'),
    AGENT_RETRY: /succeeded|成功/i.test(last.message ?? '') ? t('act.retry_ok') : t('act.retrying'),
    AGENT_REPLANNED: t('act.replanned'),
  }
  return map[last.type] ?? ''
}

const orderedAgents = computed(() => (team.value.length ? team.value : snapshotAgents.value))
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

function agentName(id: string): string {
  if (!id) return '—'
  return (
    team.value.find((a) => a.id === id)?.name ??
    snapshot.value?.agent_names?.[id] ??
    id
  )
}

async function loadTeam() {
  try {
    const res = await api.getTeam(props.taskId)
    team.value = res.agents
  } catch (err) {
    error.value = String(err)
  }
}

// --- M2: live event stream with bounded height + auto-follow ---------------
const streamEl = ref<HTMLElement | null>(null)
const following = ref(true)
const NEAR_BOTTOM_PX = 48

function onStreamScroll() {
  const el = streamEl.value
  if (!el) return
  following.value = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
}
function scrollToLatest(smooth = true) {
  const el = streamEl.value
  if (!el) return
  el.scrollTo({
    top: el.scrollHeight,
    behavior: smooth && !prefersReducedMotion() ? 'smooth' : 'auto',
  })
  following.value = true
}
// follow only while the user is at the bottom; never jumps the whole page
watch(
  () => store.events.length,
  () => {
    if (!following.value) return
    void nextTick(() => scrollToLatest(false))
  },
)

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}
function eventGlyph(type: string): 'tool' | 'artifact' | 'retry' | 'event' {
  switch (type) {
    case 'TOOL_CALLED':
      return 'tool'
    case 'TOOL_DENIED': // v0.6.11: agent tried to use a tool it is not allowed to call
      return 'retry'
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
      return 'at-info'
    case 'artifact':
      return 'at-success-text'
    case 'retry':
      return 'at-warn-text'
    default:
      return 'at-dim'
  }
}
function glyphLabel(event: ExecutionEvent): string {
  switch (event.type) {
    case 'TOOL_CALLED':
      return t(toolKindKey(event.metadata))
    case 'TOOL_DENIED':
      return t('act.tool_denied')
    case 'ARTIFACT_CREATED':
      return t('act.artifact')
    case 'AGENT_OUTPUT':
      return t('act.output')
    case 'AGENT_STARTED':
      return t('act.started')
    case 'AGENT_RETRY':
      return /succeeded|成功/i.test(event.message ?? '') ? t('act.retry_ok') : t('act.retrying')
    case 'AGENT_FAILED':
      return t('act.failed')
    case 'AGENT_REPLANNED':
      return t('act.replanned')
    default:
      return event.type.toLowerCase()
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function startTask(taskId: string) {
  cleanup()
  team.value = []
  error.value = null
  void store.loadTask(taskId).then(() => {
    void loadTeam()
    scrollToLatest(false)
  })
  store.startStream(taskId)
  pollTimer = setInterval(() => {
    if (snapshot.value?.status === 'running') void loadTeam()
  }, 4000)
}

onMounted(() => startTask(props.taskId))
watch(() => props.taskId, (id) => startTask(id))
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
  <div class="mx-auto w-full max-w-[1400px] px-6 py-8 md:px-10 md:py-10">
    <!-- Run header -->
    <div class="mb-8 flex flex-wrap items-end justify-between gap-6">
      <div class="min-w-0 max-w-[720px]">
        <p class="at-eyebrow mb-2">{{ t('exec.run') }}</p>
        <h1 class="line-clamp-2 at-t-lg font-semibold leading-snug at-fg" :title="snapshot?.task || t('exec.running')">
          {{ snapshot?.task || t('exec.running') }}
        </h1>
        <p class="mt-1.5 font-mono at-t-xs at-dim">{{ summary.runId }}</p>
      </div>
      <dl class="flex shrink-0 gap-8">
        <div>
          <dd class="at-metric">{{ summary.agents }}</dd>
          <dt class="at-t-xs at-dim">{{ t('exec.agents_count') }}</dt>
        </div>
        <div>
          <dd class="at-metric">{{ summary.layers }}</dd>
          <dt class="at-t-xs at-dim">{{ t('exec.layers_count') }}</dt>
        </div>
        <div>
          <dd class="at-metric">{{ summary.sources }}</dd>
          <dt class="at-t-xs at-dim">{{ t('exec.sources') }}</dt>
        </div>
        <div>
          <dd class="at-metric">{{ summary.evidence }}</dd>
          <dt class="at-t-xs at-dim">{{ t('exec.evidence') }}</dt>
        </div>
      </dl>
    </div>

    <!-- Overview -->
    <div v-if="isOverview" class="grid grid-cols-12 gap-8 lg:gap-12">
      <div class="col-span-12 space-y-6 lg:col-span-8">
        <p v-if="error" role="alert" class="at-t-base at-danger-text">{{ error }} <span class="at-t-xs at-muted">{{ t('common.error_reload_hint') }}</span></p>

        <!-- Agent status -->
        <section>
          <h2 class="at-eyebrow mb-3">{{ t('exec.agent_status') }}</h2>
          <ul v-if="orderedAgents.length" class="at-divide at-card overflow-hidden">
            <li
              v-for="agent in orderedAgents"
              :key="agent.id"
              class="flex items-center gap-3 px-4 py-2.5"
            >
              <AgentStatus :status="(store.agentStatuses as Record<string, string>)[agent.id] || agent.status" />
              <span class="at-t-base font-medium at-fg">{{ agent.name }}</span>
              <span v-if="agent.attempt > 1" class="at-chip">#{{ agent.attempt }}</span>
              <span class="ml-auto truncate at-t-xs at-dim" :title="agentDoing(agent.id) || ''">
                {{ agentDoing(agent.id) || '·' }}
              </span>
            </li>
          </ul>
          <div v-else class="at-card flex flex-col items-center gap-2 py-12 text-center">
            <UnitIcon name="loader" :size="20" class="at-dim at-spin" />
            <p class="at-t-base at-muted">{{ t('exec.waiting') }}</p>
          </div>
        </section>

        <!-- Live event stream -->
        <section>
          <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 class="at-eyebrow">{{ t('exec.event_stream') }}</h2>
            <p v-if="events.length" class="at-t-xs" :class="following ? 'at-dim' : 'at-warn-text'">
              {{ following ? t('exec.following') : t('exec.paused') }}
            </p>
          </div>

          <div class="relative">
            <div
              ref="streamEl"
              class="at-stream"
              role="region"
              :aria-label="t('exec.event_region')"
              tabindex="0"
              @scroll.passive="onStreamScroll"
            >
              <ol v-if="events.length" class="at-stream__list">
                <li v-for="event in events" :key="event.event_id" class="at-stream__row">
                  <span class="at-stream__time">{{ formatTime(event.timestamp) }}</span>
                  <span class="min-w-0">
                    <span class="at-stream__head">
                      <span class="at-stream__agent">{{ agentName(event.agent_id) }}</span>
                      <span class="at-stream__type" :class="glyphColor(eventGlyph(event.type))">{{ glyphLabel(event) }}</span>
                    </span>
                    <span class="at-stream__msg">{{ event.message }}</span>
                  </span>
                </li>
              </ol>
              <p v-else class="p-4 at-t-sm at-dim">{{ t('exec.no_events') }}</p>
            </div>

            <button
              v-if="!following && events.length"
              type="button"
              class="at-btn at-stream__latest"
              @click="scrollToLatest(true)"
            >
              <UnitIcon name="chevronDown" :size="14" />
              {{ t('exec.follow_latest') }}
            </button>
          </div>
        </section>
      </div>

      <!-- Right rail -->
      <aside class="col-span-12 space-y-8 lg:col-span-4">
        <div>
          <h2 class="at-eyebrow mb-3">{{ t('exec.tool_calls') }}</h2>
          <ul class="space-y-2">
            <li
              v-for="event in events.filter((e) => e.type === 'TOOL_CALLED').reverse().slice(0, 8)"
              :key="event.event_id"
              class="flex min-w-0 items-center justify-between gap-2 at-t-sm"
            >
              <span class="truncate font-mono at-fg" :title="event.metadata.tool || 'tool'">{{ event.metadata.tool || 'tool' }}</span>
              <span class="at-chip">
                <span class="at-dot" :class="toolKindDot(event.metadata)" style="width: 5px; height: 5px" aria-hidden="true" />
                {{ t(toolKindKey(event.metadata)) }}
              </span>
            </li>
            <li v-if="!events.some((e) => e.type === 'TOOL_CALLED')" class="at-t-sm at-dim">
              {{ t('exec.no_tool_calls') }}
            </li>
          </ul>
        </div>

        <div>
          <h2 class="at-eyebrow mb-3">{{ t('exec.provenance') }}</h2>
          <div class="flex gap-8">
            <div>
              <p class="at-metric">{{ summary.evidence }}</p>
              <p class="at-t-xs at-dim">{{ t('exec.evidence') }}</p>
            </div>
            <div>
              <p class="at-metric">{{ summary.sources }}</p>
              <p class="at-t-xs at-dim">{{ t('exec.sources') }}</p>
            </div>
          </div>
          <p class="mt-3 at-t-xs leading-relaxed at-dim">{{ t('exec.mode_truth') }}</p>
        </div>
      </aside>
    </div>

    <!-- Child phase (team / artifacts / result) -->
    <RouterView v-else v-slot="{ Component }">
      <component :is="Component" :key="props.taskId + String(route.name)" :task-id="props.taskId" />
    </RouterView>
  </div>
</template>
