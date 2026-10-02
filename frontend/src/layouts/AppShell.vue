<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'

const route = useRoute()
const store = useTeamStore()
const { t, locale, toggleLocale } = useI18n()

const taskId = computed(() => route.params.taskId as string | undefined)
const phase = computed(() => String(route.name ?? 'workspace'))
const mainEl = ref<HTMLElement | null>(null)

// O5: focus the main region only on real route changes (never on data refresh)
watch(
  () => route.fullPath,
  () => {
    void nextTick(() => {
      if (!mainEl.value) return
      mainEl.value.scrollTop = 0
      mainEl.value.focus({ preventScroll: true })
    })
  },
)

const navItems = computed(() => [
  { key: 'workspace', label: t('nav.workspace'), to: '/', icon: 'workflow' as const, active: phase.value === 'workspace' },
  { key: 'runs', label: t('nav.runs'), to: taskId.value ? `/tasks/${taskId.value}` : '/', icon: 'layers' as const, active: phase.value === 'execution', disabled: !taskId.value },
  { key: 'teams', label: t('nav.team'), to: taskId.value ? `/tasks/${taskId.value}/team` : '/', icon: 'users' as const, active: phase.value === 'team', disabled: !taskId.value },
  { key: 'artifacts', label: t('nav.artifacts'), to: taskId.value ? `/tasks/${taskId.value}/artifacts` : '/', icon: 'fileText' as const, active: phase.value === 'artifacts', disabled: !taskId.value },
  { key: 'result', label: t('nav.result'), to: taskId.value ? `/tasks/${taskId.value}/result` : '/', icon: 'check' as const, active: phase.value === 'result', disabled: !taskId.value },
])

const recentTasks = computed(() => store.tasks.slice(0, 6))
const runStatus = computed(() => store.current?.status ?? 'idle')
const mode = computed(() => store.current?.mode ?? 'offline')

// M3 — one stable, atomic status region. It only changes on meaningful run
// transitions (start / agent completion / retry / failure / topic degradation),
// never on every high-frequency execution event.
const announcement = computed(() => {
  const snap = store.current
  if (!snap) return t('a11y.status_idle')
  const results = Object.values(snap.agent_results ?? {})
  const total = Object.keys(snap.agent_names ?? {}).length || results.length
  const completed = results.filter((r) => r.status === 'success').length
  const failed = results.filter((r) => r.status === 'failed').length
  const retries = store.events.filter((e) => e.type === 'AGENT_RETRY').length
  const degraded = store.events.some((e) => e.type === 'SYNTHESIS_FAILED')
  const parts: string[] = []
  if (snap.status === 'running') parts.push(t('a11y.status_running', { total }))
  if (completed) parts.push(t('a11y.status_completed_agents', { n: completed }))
  if (failed) parts.push(t('a11y.status_failed_agents', { n: failed }))
  if (retries) parts.push(t('a11y.status_retries', { n: retries }))
  if (degraded) parts.push(t('a11y.status_degraded'))
  if (snap.status === 'success') parts.push(t('a11y.status_done'))
  else if (snap.status === 'partial_success') parts.push(t('a11y.status_partial'))
  else if (snap.status === 'failed') parts.push(t('a11y.status_failed'))
  return parts.join(' · ') || t('a11y.status_idle')
})

function runDotClass(status: string): string {
  switch (status) {
    case 'success':
      return 'at-success-text'
    case 'running':
      return 'at-info at-status-pulse'
    case 'failed':
      return 'at-danger-text'
    case 'partial_success':
      return 'at-warn-text'
    default:
      return 'at-dim'
  }
}

function statusChipClass(status: string): string {
  switch (status) {
    case 'success':
      return 'at-chip--success'
    case 'running':
      return 'at-chip--info'
    case 'failed':
      return 'at-chip--danger'
    case 'partial_success':
      return 'at-chip--warn'
    default:
      return 'at-chip--neutral'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'success':
      return t('runstatus.success')
    case 'running':
      return t('runstatus.running')
    case 'failed':
      return t('runstatus.failed')
    case 'partial_success':
      return t('runstatus.partial')
    default:
      return status
  }
}
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <a href="#main" class="at-skip">{{ t('a11y.skip') }}</a>
    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>

    <!-- Sidebar (≥768px) — persistent primary navigation -->
    <aside class="at-surface hidden w-60 shrink-0 flex-col border-r at-border md:flex">
      <RouterLink to="/" class="flex items-center gap-2.5 px-5 py-5" :aria-label="t('app.name')">
        <span class="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--at-brand)] font-mono at-t-xs font-bold text-[var(--at-brand-fg)]">
          AT
        </span>
        <span class="at-h2 at-t-md">AutoTeam</span>
      </RouterLink>

      <nav class="flex-1 space-y-1 overflow-y-auto px-3" :aria-label="t('nav.workspace')">
        <p class="at-eyebrow mb-2 px-1">{{ t('sidebar.workspace') }}</p>
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          class="at-nav-item"
          :class="[item.active ? 'is-active' : '', item.disabled ? 'is-disabled' : '']"
          :aria-current="item.active ? 'page' : undefined"
        >
          <UnitIcon :name="item.icon" :size="16" />
          <span class="truncate">{{ item.label }}</span>
        </RouterLink>

        <template v-if="recentTasks.length">
          <p class="at-eyebrow mb-2 mt-7 px-1">{{ t('sidebar.recent') }}</p>
          <RouterLink
            v-for="run in recentTasks"
            :key="run.task_id"
            :to="{ name: 'execution', params: { taskId: run.task_id } }"
            class="block truncate rounded-md px-2 py-1.5 font-mono at-t-xs text-[var(--at-fg-dim)] transition-colors hover:bg-[var(--at-surface-2)] hover:text-[var(--at-fg)]"
            :title="run.task"
          >
            {{ run.task }}
          </RouterLink>
        </template>
      </nav>

      <div class="at-border-t px-5 py-4">
        <div class="flex items-center justify-between at-t-xs">
          <span class="at-dim">{{ t('app.mode_label') }}</span>
          <span class="inline-flex items-center gap-1.5 font-medium" :class="mode === 'real' ? 'at-info' : 'at-dim'">
            <span class="at-dot" style="width: 6px; height: 6px" />
            {{ t(mode === 'real' ? 'mode.real' : 'mode.offline') }}
          </span>
        </div>
        <p class="mt-1.5 font-mono at-t-xs text-[var(--at-fg-dim)]">{{ t('app.version') }}</p>
      </div>
    </aside>

    <!-- Main column -->
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Top bar: run context + mode + locale -->
      <header class="at-surface sticky top-0 z-30 flex h-14 shrink-0 items-center gap-4 border-b at-border px-5 md:px-8">
        <div class="flex min-w-0 flex-1 items-center gap-3">
          <template v-if="store.current">
            <span class="at-dot shrink-0" :class="runDotClass(runStatus)" aria-hidden="true" />
            <span class="truncate at-t-base font-medium text-[var(--at-fg)]" :title="store.current.task">
              {{ store.current.task }}
            </span>
            <span v-if="runStatus !== 'idle'" class="at-chip shrink-0" :class="statusChipClass(runStatus)">
              {{ statusLabel(runStatus) }}
            </span>
          </template>
          <template v-else>
            <span class="at-t-base at-dim">{{ t('topbar.idle') }}</span>
          </template>
        </div>

        <div class="flex shrink-0 items-center gap-2">
          <span class="at-chip" :title="t('app.mode_label')">
            <span
              class="at-dot"
              :class="mode === 'real' ? 'at-dot--real' : 'at-dot--offline'"
              style="width: 6px; height: 6px"
              aria-hidden="true"
            />
            {{ t(mode === 'real' ? 'mode.real' : 'mode.offline') }}
          </span>
          <button type="button" class="at-btn at-btn-ghost" @click="toggleLocale">
            {{ locale === 'zh' ? 'EN' : '中文' }}
          </button>
        </div>
      </header>

      <!-- Adaptive navigation for small screens (nav must stay reachable) -->
      <nav class="at-surface flex shrink-0 gap-1 overflow-x-auto border-b at-border px-3 py-2 md:hidden" :aria-label="t('nav.workspace')">
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          class="at-nav-item whitespace-nowrap"
          :class="[item.active ? 'is-active' : '', item.disabled ? 'is-disabled' : '']"
          :aria-current="item.active ? 'page' : undefined"
        >
          <UnitIcon :name="item.icon" :size="15" />
          {{ item.label }}
        </RouterLink>
      </nav>

      <main id="main" ref="mainEl" class="min-h-0 flex-1 overflow-y-auto" tabindex="-1">
        <RouterView v-slot="{ Component }">
          <component
            :is="Component"
            :key="String(route.params.taskId ?? route.name ?? 'root')"
            class="at-route-in"
          />
        </RouterView>
      </main>
    </div>
  </div>
</template>
