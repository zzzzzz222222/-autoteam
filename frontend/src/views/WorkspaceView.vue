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

// static product narrative (clearly marked, not faked run state)
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
  if (!task.value.trim()) return
  submitting.value = true
  error.value = null
  try {
    const created = await api.createTask(task.value.trim(), mode.value)
    await store.loadTask(created.task_id)
    store.startStream(created.task_id)
    await router.push({ name: 'execution', params: { taskId: created.task_id } })
  } catch (err) {
    error.value = String(err)
  } finally {
    submitting.value = false
  }
}

function relativeTime(timestamp: number): string {
  const seconds = Math.floor(Date.now() / 1000 - timestamp)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

const recentRuns = computed(() => store.tasks.slice(0, 6))

onMounted(() => {
  void store.fetchList()
})
</script>

<template>
  <div class="mx-auto w-full max-w-[1200px] px-10 py-12">
    <!-- Hero: left aligned, large -->
    <div class="mb-10">
      <p class="tok-eyebrow mb-3">{{ t('workspace.eyebrow') }}</p>
      <h1 class="tok-hero">{{ t('workspace.hero') }}</h1>
      <p class="mt-4 max-w-2xl text-[18px] leading-relaxed text-zinc-500">{{ t('workspace.subtitle') }}</p>
    </div>

    <!-- Task composer: the visual core, wide and prominent -->
    <div
      class="at-card overflow-hidden shadow-sm focus-within:border-blue-500 focus-within:ring-4 focus-within:ring-blue-500/10"
      style="max-width: 940px"
    >
      <textarea
        v-model="task"
        rows="6"
        class="w-full resize-none bg-transparent px-6 py-5 text-[17px] leading-relaxed text-zinc-900 outline-none placeholder:text-zinc-400"
        :placeholder="t('workspace.input_placeholder')"
      ></textarea>
      <div class="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/60 px-5 py-3">
        <div class="flex items-center gap-5 text-[14px]">
          <label class="flex cursor-pointer items-center gap-2 text-zinc-600">
            <input v-model="mode" type="radio" value="real" class="accent-blue-600 h-4 w-4" />
            Real
          </label>
          <label class="flex cursor-pointer items-center gap-2 text-zinc-600">
            <input v-model="mode" type="radio" value="offline" class="accent-blue-600 h-4 w-4" />
            Offline
          </label>
        </div>
        <button
          type="button"
          :disabled="submitting || !task.trim()"
          class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-[15px] font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          @click="createAndRun"
        >
          {{ submitting ? t('workspace.starting') : t('workspace.run') }}
          <UnitIcon name="arrowRight" :size="16" />
        </button>
      </div>
    </div>

    <p v-if="error" class="mt-4 text-[15px] text-red-600">{{ error }}</p>
    <p v-else-if="submitting" class="mt-4 text-[15px] text-zinc-400">{{ t('workspace.forming') }}</p>

    <!-- Example tasks: pill cards -->
    <div class="mt-12" style="max-width: 940px">
      <p class="tok-eyebrow mb-4">{{ t('workspace.examples') }}</p>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <button
          v-for="example in examples"
          :key="example.labelKey"
          type="button"
          class="at-card group flex items-center gap-3 px-4 py-4 text-left transition-colors hover:border-zinc-400 hover:bg-white"
          @click="useExample(example)"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 transition-colors group-hover:bg-blue-50 group-hover:text-blue-600">
            <UnitIcon :name="example.icon" :size="17" />
          </span>
          <span class="text-[15px] font-medium text-zinc-800">{{ t(example.labelKey) }}</span>
        </button>
      </div>
    </div>

    <!-- How AutoTeam Works: visual product narrative (static, clearly labeled) -->
    <div class="mt-16" style="max-width: 940px">
      <p class="tok-eyebrow mb-6">{{ t('ws.title') }}</p>
      <div class="grid grid-cols-1 gap-0 sm:grid-cols-4 lg:grid-cols-8">
        <template v-for="(step, i) in journey" :key="step.key">
          <div class="flex flex-col items-start pr-6">
            <span class="font-mono text-[12px] font-medium text-blue-600">0{{ i + 1 }}</span>
            <p class="mt-1.5 text-[15px] font-semibold text-zinc-900">{{ step.key }}</p>
            <p class="mt-0.5 text-[13px] leading-relaxed text-zinc-400">{{ step.d }}</p>
          </div>
          <div v-if="i < journey.length - 1" class="hidden py-8 pr-6 lg:block">
            <UnitIcon name="arrowRight" :size="18" class="text-zinc-300" />
          </div>
        </template>
      </div>
    </div>

    <!-- Recent runs: work history with visual weight -->
    <div v-if="recentRuns.length" class="mt-16" style="max-width: 940px">
      <p class="tok-eyebrow mb-4">{{ t('workspace.recent') }}</p>
      <ul class="divide-y divide-zinc-200 border-t border-zinc-200">
        <li v-for="run in recentRuns" :key="run.task_id">
          <RouterLink
            :to="{ name: 'execution', params: { taskId: run.task_id } }"
            class="group flex items-center justify-between gap-6 py-4"
          >
            <div class="flex min-w-0 items-center gap-4">
              <span
                class="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                :class="{
                  'bg-emerald-500': run.status === 'success',
                  'bg-blue-500': run.status === 'running',
                  'bg-red-500': run.status === 'failed',
                  'bg-amber-500': run.status === 'partial_success',
                  'bg-zinc-300': !['success', 'running', 'failed', 'partial_success'].includes(run.status),
                }"
              />
              <div class="min-w-0">
                <p class="truncate text-[15px] font-medium text-zinc-800 group-hover:text-blue-700" :title="run.task">
                  {{ run.task }}
                </p>
                <p class="mt-0.5 text-[13px] text-zinc-400">
                  {{ Object.keys(run.agent_names || {}).length }} agents
                  · {{ (run.layers || []).length }} layers
                  · {{ (run.final_artifact?.sources || []).length }} sources
                </p>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-5 text-[13px] text-zinc-400">
              <span class="rounded-full border border-zinc-200 px-2.5 py-0.5 text-[12px] font-medium">
                {{ run.mode }}
              </span>
              <span class="font-mono">{{ relativeTime(run.created_at) }}</span>
            </div>
          </RouterLink>
        </li>
      </ul>
    </div>
  </div>
</template>