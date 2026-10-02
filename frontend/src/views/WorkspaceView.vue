<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'

const router = useRouter()
const store = useTeamStore()
const { t } = useI18n()

const task = ref('')
const mode = ref<'real' | 'offline'>('offline')
const submitting = ref(false)
const error = ref<string | null>(null)

const examples = [
  { labelKey: 'workspace.ex_market', valueKey: 'workspace.ex_market_value', icon: 'search' as const },
  { labelKey: 'workspace.ex_ecommerce', valueKey: 'workspace.ex_ecommerce_value', icon: 'box' as const },
  { labelKey: 'workspace.ex_saas', valueKey: 'workspace.ex_saas_value', icon: 'layers' as const },
]

// Static product narrative — clearly a description, never faked run state.
const journey = computed(() => [
  { key: t('ws.j1'), d: t('ws.j1d') },
  { key: t('ws.j2'), d: t('ws.j2d') },
  { key: t('ws.j3'), d: t('ws.j3d') },
  { key: t('ws.j4'), d: t('ws.j4d') },
  { key: t('ws.j5'), d: t('ws.j5d') },
  { key: t('ws.j6'), d: t('ws.j6d') },
  { key: t('ws.j7'), d: t('ws.j7d') },
])

function useExample(e: (typeof examples)[number]) {
  task.value = t(e.valueKey)
}

async function createAndRun() {
  if (!task.value.trim() || submitting.value) return
  submitting.value = true
  error.value = null
  try {
    const created = await api.createTask(task.value.trim(), mode.value)
    await store.loadTask(created.task_id)
    store.startStream(created.task_id)
    await router.push({ name: 'execution', params: { taskId: created.task_id } })
  } catch (err) {
    error.value = `${t('common.request_failed')} — ${String(err)}`
  } finally {
    submitting.value = false
  }
}

function relativeTime(timestamp: number): string {
  const seconds = Math.floor(Date.now() / 1000 - timestamp)
  if (seconds < 60) return `${seconds} ${t('common.ago_s')}`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} ${t('common.ago_m')}`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} ${t('common.ago_h')}`
  return `${Math.floor(seconds / 86400)} ${t('common.ago_d')}`
}

function runStatusClass(status: string): string {
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

const recentRuns = computed(() => store.tasks.slice(0, 6))

const errorInfo = computed(() => {
  if (!error.value) return null
  const network = /failed to fetch|networkerror|load failed|network request failed/i.test(error.value)
  return {
    reason: network ? t('common.error_network') : t('common.request_failed'),
    detail: error.value,
  }
})

onMounted(() => {
  void store.fetchList()
})
</script>

<template>
  <div class="mx-auto w-full max-w-[1180px] px-6 py-10 md:px-10 md:py-14">
    <!-- Hero -->
    <div class="at-fade-in mb-10">
      <p class="at-eyebrow mb-3">{{ t('workspace.eyebrow') }}</p>
      <h1 class="at-h1 max-w-3xl">{{ t('workspace.hero') }}</h1>
      <p class="mt-4 max-w-2xl at-t-lg leading-relaxed at-muted md:at-t-lg">
        {{ t('workspace.subtitle') }}
      </p>
    </div>

    <!-- Composer -->
    <form class="at-panel overflow-hidden md:max-w-[920px]" @submit.prevent="createAndRun">
      <div class="p-4 md:p-5">
        <label for="task-input" class="at-eyebrow mb-2 block">{{ t('workspace.input_label') }}</label>
        <textarea
          id="task-input"
          v-model="task"
          rows="5"
          class="at-textarea resize-none at-t-lg"
          :placeholder="t('workspace.input_placeholder')"
          :aria-describedby="error ? 'task-error' : undefined"
        ></textarea>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 border-t at-border px-4 py-3 md:px-5">
        <fieldset class="flex items-center gap-3">
          <legend class="sr-only">{{ t('workspace.mode_label') }}</legend>
          <div class="at-seg">
            <label>
              <input v-model="mode" type="radio" value="offline" name="run-mode" />
              {{ t('workspace.mode_offline') }}
            </label>
            <label>
              <input v-model="mode" type="radio" value="real" name="run-mode" />
              {{ t('workspace.mode_real') }}
            </label>
          </div>
        </fieldset>

        <button type="submit" class="at-btn at-btn-primary" :disabled="submitting || !task.trim()">
          <UnitIcon v-if="submitting" name="loader" :size="15" class="at-spin" />
          <UnitIcon v-else name="play" :size="15" />
          {{ submitting ? t('workspace.starting') : t('workspace.run') }}
        </button>
      </div>
    </form>

    <div v-if="errorInfo" id="task-error" role="alert" class="mt-3 at-t-base at-danger-text">
      <p class="flex items-center gap-2">
        <UnitIcon name="alertTriangle" :size="15" />
        {{ errorInfo.reason }}
      </p>
      <p class="mt-1 block font-mono at-t-xs at-dim">{{ errorInfo.detail }}</p>
      <p class="mt-1 block at-t-xs at-muted">{{ t('common.error_hint') }}</p>
    </div>
    <p v-else-if="submitting" class="mt-3 flex items-center gap-2 at-t-base at-muted">
      <UnitIcon name="loader" :size="15" class="at-spin" />
      {{ t('workspace.forming') }}
    </p>

    <!-- Examples -->
    <section class="mt-12 md:max-w-[920px]" :aria-label="t('workspace.examples')">
      <h2 class="at-eyebrow mb-4">{{ t('workspace.examples') }}</h2>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <button
          v-for="example in examples"
          :key="example.labelKey"
          type="button"
          class="at-card group flex items-center gap-3 px-4 py-4 text-left transition-colors hover:border-[var(--at-border-strong)]"
          @click="useExample(example)"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md at-inset at-dim transition-colors group-hover:text-[var(--at-info)]">
            <UnitIcon :name="example.icon" :size="16" />
          </span>
          <span class="at-t-base font-medium at-fg">{{ t(example.labelKey) }}</span>
        </button>
      </div>
    </section>

    <!-- How it works -->
    <section class="mt-16 md:max-w-[920px]" :aria-label="t('ws.title')">
      <h2 class="at-eyebrow mb-6">{{ t('ws.title') }}</h2>
      <ol class="grid grid-cols-2 gap-x-6 gap-y-7 sm:grid-cols-4 lg:grid-cols-7">
        <li v-for="(step, i) in journey" :key="step.key" class="flex flex-col">
          <span class="at-mono at-t-xs font-semibold at-dim">{{ String(i + 1).padStart(2, '0') }}</span>
          <p class="mt-1.5 at-t-base font-semibold at-fg">{{ step.key }}</p>
          <p class="mt-0.5 at-t-xs leading-relaxed at-dim">{{ step.d }}</p>
        </li>
      </ol>
    </section>

    <!-- Recent runs -->
    <section v-if="recentRuns.length" class="mt-16 md:max-w-[920px]" :aria-label="t('workspace.recent')">
      <h2 class="at-eyebrow mb-4">{{ t('workspace.recent') }}</h2>
      <ul class="at-divide at-card overflow-hidden">
        <li v-for="run in recentRuns" :key="run.task_id">
          <RouterLink
            :to="{ name: 'execution', params: { taskId: run.task_id } }"
            class="group flex items-center justify-between gap-4 px-4 py-3.5 transition-colors hover:bg-[var(--at-surface-2)]"
          >
            <div class="flex min-w-0 items-center gap-3">
              <span class="at-dot shrink-0" :class="runStatusClass(run.status)" aria-hidden="true" />
              <div class="min-w-0">
                <p class="truncate at-t-base font-medium at-fg" :title="run.task">{{ run.task }}</p>
                <p class="mt-0.5 font-mono at-t-xs at-dim">
                  {{ Object.keys(run.agent_names || {}).length }} {{ t('common.agents') }} ·
                  {{ (run.layers || []).length }} {{ t('common.layers') }} ·
                  {{ (run.final_artifact?.sources || []).length }} {{ t('common.sources') }}
                </p>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-3 font-mono at-t-xs at-dim">
              <span class="at-chip">{{ t(run.mode === 'real' ? 'mode.real' : 'mode.offline') }}</span>
              <span class="at-num">{{ relativeTime(run.created_at) }}</span>
            </div>
          </RouterLink>
        </li>
      </ul>
    </section>
  </div>
</template>
