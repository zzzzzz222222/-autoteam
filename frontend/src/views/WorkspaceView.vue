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
  { labelKey: 'workspace.ex_market', valueKey: 'workspace.ex_market_value' },
  { labelKey: 'workspace.ex_ecommerce', valueKey: 'workspace.ex_ecommerce_value' },
  { labelKey: 'workspace.ex_saas', valueKey: 'workspace.ex_saas_value' },
]

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
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

const recentRuns = computed(() => store.tasks.slice(0, 6))

onMounted(() => {
  void store.fetchList()
})
</script>

<template>
  <div class="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-8 py-16">
    <!-- Hero / composer -->
    <div class="mb-14">
      <p class="tok-eyebrow mb-3">{{ t('workspace.eyebrow') }}</p>
      <h1 class="text-[28px] font-semibold leading-tight tracking-tight text-zinc-900">
        {{ t('workspace.hero') }}
      </h1>
      <p class="mt-2 text-[15px] text-zinc-500">{{ t('workspace.subtitle') }}</p>
    </div>

    <!-- Big task composer (run is part of the input, not a separate card) -->
    <div class="rounded-lg border border-zinc-300 bg-white focus-within:border-zinc-900 focus-within:ring-2 focus-within:ring-zinc-900/5">
      <textarea
        v-model="task"
        rows="4"
        class="w-full resize-none bg-transparent px-4 py-3 text-[15px] leading-relaxed text-zinc-900 outline-none placeholder:text-zinc-400"
        :placeholder="t('workspace.input_placeholder')"
      ></textarea>
      <div class="flex items-center justify-between border-t border-zinc-100 px-3 py-2">
        <div class="flex items-center gap-4 px-1 text-[13px]">
          <label class="flex cursor-pointer items-center gap-1.5 text-zinc-500">
            <input v-model="mode" type="radio" value="real" class="accent-zinc-900" />
            Real
          </label>
          <label class="flex cursor-pointer items-center gap-1.5 text-zinc-500">
            <input v-model="mode" type="radio" value="offline" class="accent-zinc-900" />
            Offline
          </label>
        </div>
        <button
          type="button"
          :disabled="submitting || !task.trim()"
          class="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3.5 py-1.5 text-[13px] font-medium text-white transition-all hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40"
          @click="createAndRun"
        >
          {{ submitting ? t('workspace.starting') : t('workspace.run') }}
          <UnitIcon name="arrowRight" :size="14" />
        </button>
      </div>
    </div>

    <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
    <p v-else-if="submitting" class="mt-3 text-sm text-zinc-400">
      {{ t('workspace.forming') }}
    </p>

    <!-- Examples: text links, not cards -->
    <div class="mt-10">
      <p class="tok-eyebrow mb-2.5">{{ t('workspace.examples') }}</p>
      <div class="flex flex-wrap gap-x-5 gap-y-2">
        <button
          v-for="example in examples"
          :key="example.labelKey"
          type="button"
          class="text-[13px] text-zinc-500 underline-offset-4 transition-colors hover:text-zinc-900 hover:underline"
          @click="useExample(example)"
        >
          {{ t(example.labelKey) }}
        </button>
      </div>
    </div>

    <!-- Recent runs: work history list -->
    <div v-if="recentRuns.length" class="mt-12">
      <p class="tok-eyebrow mb-2.5">{{ t('workspace.recent') }}</p>
      <ul class="divide-y divide-zinc-200 border-t border-zinc-200">
        <li v-for="run in recentRuns" :key="run.task_id">
          <RouterLink
            :to="{ name: 'execution', params: { taskId: run.task_id } }"
            class="group flex items-center justify-between gap-4 py-2.5"
          >
            <div class="flex min-w-0 items-center gap-3">
              <span
                class="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                :class="{
                  'bg-emerald-500': run.status === 'success',
                  'bg-blue-500': run.status === 'running',
                  'bg-red-500': run.status === 'failed',
                  'bg-amber-500': run.status === 'partial_success',
                  'bg-zinc-300': !['success', 'running', 'failed', 'partial_success'].includes(run.status),
                }"
              />
              <span class="truncate text-[13px] text-zinc-700 group-hover:text-zinc-900">
                {{ run.task }}
              </span>
            </div>
            <div class="flex shrink-0 items-center gap-4 text-[11px] text-zinc-400">
              <span>{{ run.mode }}</span>
              <span class="font-mono">{{ relativeTime(run.created_at) }}</span>
            </div>
          </RouterLink>
        </li>
      </ul>
    </div>
  </div>
</template>