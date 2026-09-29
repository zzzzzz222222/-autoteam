<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'

const router = useRouter()
const store = useTeamStore()
const { t } = useI18n()

const task = ref('分析当前 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案')
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

onMounted(() => {
  void store.fetchList()
})
</script>

<template>
  <div class="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-6 py-16">
    <div class="mb-8 text-center">
      <h1 class="text-3xl font-semibold tracking-tight text-zinc-900">{{ t('workspace.title') }}</h1>
      <p class="mt-2 text-sm text-zinc-500">{{ t('workspace.subtitle') }}</p>
    </div>

    <div class="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <label class="mb-2 block text-sm font-medium text-zinc-700" for="task-input">
        {{ t('workspace.input_label') }}
      </label>
      <textarea
        id="task-input"
        v-model="task"
        rows="4"
        class="w-full resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition-colors focus:border-zinc-500"
        :placeholder="t('workspace.input_placeholder')"
      ></textarea>

      <div class="mt-4 flex items-center justify-between">
        <fieldset class="flex items-center gap-4 text-sm">
          <legend class="sr-only">{{ t('workspace.mode_label') }}</legend>
          <label class="flex cursor-pointer items-center gap-1.5">
            <input v-model="mode" type="radio" value="offline" class="accent-zinc-900" />
            {{ t('workspace.mode_offline') }}
          </label>
          <label class="flex cursor-pointer items-center gap-1.5">
            <input v-model="mode" type="radio" value="real" class="accent-zinc-900" />
            {{ t('workspace.mode_real') }}
          </label>
        </fieldset>
        <button
          type="button"
          :disabled="submitting || !task.trim()"
          class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
          @click="createAndRun"
        >
          {{ submitting ? t('workspace.starting') : t('workspace.run') }}
        </button>
      </div>
      <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
      <p v-else-if="submitting" class="mt-3 text-sm text-zinc-400">
        {{ t('workspace.forming') }}
      </p>
    </div>

    <div class="mt-8">
      <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
        {{ t('workspace.examples') }}
      </p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="example in examples"
          :key="example.labelKey"
          type="button"
          class="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900"
          @click="useExample(example)"
        >
          {{ t(example.labelKey) }}
        </button>
      </div>
    </div>

    <div v-if="store.tasks.length" class="mt-10">
      <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
        {{ t('workspace.recent') }}
      </p>
      <ul class="divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
        <li v-for="run in store.tasks" :key="run.task_id">
          <RouterLink
            :to="{ name: 'execution', params: { taskId: run.task_id } }"
            class="flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-zinc-50"
          >
            <span class="truncate text-zinc-700">{{ run.task }}</span>
            <span class="flex shrink-0 items-center gap-3">
              <span class="text-xs text-zinc-400">{{ run.mode }}</span>
              <span class="text-xs font-medium text-zinc-500">{{ run.status }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </div>
</template>