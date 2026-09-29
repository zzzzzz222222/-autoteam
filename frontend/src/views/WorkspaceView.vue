<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'

const router = useRouter()
const store = useTeamStore()

const task = ref('分析当前 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案')
const mode = ref<'real' | 'offline'>('offline')
const submitting = ref(false)
const error = ref<string | null>(null)

const examples = [
  { label: 'AI Agent Market Research', value: '分析当前 AI Agent 市场的发展情况，重点关注产品方向、企业应用场景和技术趋势' },
  { label: 'E-commerce Architecture', value: '设计一个 FastAPI 电商后端系统，包含需求、架构、数据库与测试方案' },
  { label: 'SaaS Market Entry', value: '制定 SaaS 产品进入某行业的市场策略，包含客户洞察、竞品分析与财务评估' },
]

function useExample(e: string) {
  task.value = e
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
      <h1 class="text-3xl font-semibold tracking-tight text-zinc-900">AutoTeam</h1>
      <p class="mt-2 text-sm text-zinc-500">
        Dynamic multi-agent execution — describe a task and watch a team plan, collaborate and deliver.
      </p>
    </div>

    <div class="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <label class="mb-2 block text-sm font-medium text-zinc-700" for="task-input">
        What do you want your AI team to do?
      </label>
      <textarea
        id="task-input"
        v-model="task"
        rows="4"
        class="w-full resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition-colors focus:border-zinc-500"
        placeholder="Describe your task…"
      ></textarea>

      <div class="mt-4 flex items-center justify-between">
        <fieldset class="flex items-center gap-4 text-sm">
          <legend class="sr-only">Execution mode</legend>
          <label class="flex cursor-pointer items-center gap-1.5">
            <input v-model="mode" type="radio" value="offline" class="accent-zinc-900" />
            Offline
          </label>
          <label class="flex cursor-pointer items-center gap-1.5">
            <input v-model="mode" type="radio" value="real" class="accent-zinc-900" />
            Real LLM
          </label>
        </fieldset>
        <button
          type="button"
          :disabled="submitting || !task.trim()"
          class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
          @click="createAndRun"
        >
          {{ submitting ? 'Starting…' : 'Build Team & Run' }}
        </button>
      </div>
      <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
      <p v-else-if="submitting" class="mt-3 text-sm text-zinc-400">
        Forming the dynamic team and starting execution…
      </p>
    </div>

    <div class="mt-8">
      <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
        Example tasks
      </p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="example in examples"
          :key="example.label"
          type="button"
          class="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900"
          @click="useExample(example.value)"
        >
          {{ example.label }}
        </button>
      </div>
    </div>

    <div v-if="store.tasks.length" class="mt-10">
      <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
        Recent runs (this backend session)
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