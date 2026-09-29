<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'

const route = useRoute()
const store = useTeamStore()
const { t, locale, toggleLocale } = useI18n()

const taskId = computed(() => route.params.taskId as string | undefined)
const phase = computed(() => String(route.name ?? 'workspace'))

const navItems = computed(() => [
  {
    key: 'workspace',
    label: t('nav.workspace'),
    to: '/',
    icon: 'workflow' as const,
    active: phase.value === 'workspace',
  },
  {
    key: 'runs',
    label: t('nav.runs'),
    to: taskId.value ? `/tasks/${taskId.value}` : '/',
    icon: 'layers' as const,
    active: phase.value === 'execution',
    disabled: !taskId.value,
  },
  {
    key: 'teams',
    label: t('nav.team'),
    to: taskId.value ? `/tasks/${taskId.value}/team` : '/',
    icon: 'users' as const,
    active: phase.value === 'team',
    disabled: !taskId.value,
  },
  {
    key: 'artifacts',
    label: t('nav.artifacts'),
    to: taskId.value ? `/tasks/${taskId.value}/artifacts` : '/',
    icon: 'fileText' as const,
    active: phase.value === 'artifacts',
    disabled: !taskId.value,
  },
  {
    key: 'result',
    label: t('nav.result'),
    to: taskId.value ? `/tasks/${taskId.value}/result` : '/',
    icon: 'check' as const,
    active: phase.value === 'result',
    disabled: !taskId.value,
  },
])

const recentTasks = computed(() => store.tasks.slice(0, 5))
const runStatus = computed(() => store.current?.status ?? 'idle')
const mode = computed(() => store.current?.mode ?? 'offline')

function runStatusClass(status: string): string {
  switch (status) {
    case 'success':
      return 'bg-emerald-500'
    case 'running':
      return 'bg-blue-500 at-status-pulse'
    case 'failed':
      return 'bg-red-500'
    case 'partial_success':
      return 'bg-amber-500'
    default:
      return 'bg-zinc-300'
  }
}

function statusPillClass(status: string): string {
  switch (status) {
    case 'success':
      return 'bg-emerald-50 text-emerald-700'
    case 'running':
      return 'bg-blue-50 text-blue-600'
    case 'failed':
      return 'bg-red-50 text-red-600'
    case 'partial_success':
      return 'bg-amber-50 text-amber-700'
    default:
      return 'bg-zinc-100 text-zinc-500'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'success':
      return 'SUCCESS'
    case 'running':
      return 'RUNNING'
    case 'failed':
      return 'FAILED'
    case 'partial_success':
      return 'PARTIAL'
    default:
      return status.toUpperCase()
  }
}
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <!-- Sidebar: 240px product navigation -->
    <aside class="hidden w-60 shrink-0 flex-col border-r border-zinc-200 bg-white md:flex">
      <RouterLink to="/" class="flex items-center gap-2.5 px-6 py-6">
        <span class="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 text-[13px] font-bold text-white">
          A
        </span>
        <span class="text-[16px] font-semibold tracking-tight">AutoTeam</span>
      </RouterLink>

      <nav class="flex-1 space-y-1 px-4">
        <p class="tok-eyebrow mb-2 px-2">{{ t('sidebar.workspace') }}</p>
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          class="flex items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] transition-colors"
          :class="[
            item.active
              ? 'bg-zinc-100 font-semibold text-zinc-900'
              : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800',
            item.disabled ? 'pointer-events-none opacity-40' : '',
          ]"
        >
          <UnitIcon :name="item.icon" :size="17" />
          {{ item.label }}
        </RouterLink>

        <p v-if="recentTasks.length" class="tok-eyebrow mb-2 mt-7 px-2">{{ t('sidebar.recent') }}</p>
        <RouterLink
          v-for="run in recentTasks"
          :key="run.task_id"
          :to="{ name: 'execution', params: { taskId: run.task_id } }"
          class="block truncate rounded-lg px-2.5 py-1.5 text-[13px] text-zinc-400 transition-colors hover:bg-zinc-50 hover:text-zinc-700"
        >
          {{ run.task }}
        </RouterLink>
      </nav>

      <div class="border-t border-zinc-100 px-6 py-5">
        <div class="flex items-center justify-between text-[13px]">
          <span class="text-zinc-400">{{ t('app.mode_label') }}</span>
          <span
            class="inline-flex items-center gap-1.5 font-medium"
            :class="mode === 'real' ? 'text-emerald-600' : 'text-zinc-500'"
          >
            <span class="inline-block h-1.5 w-1.5 rounded-full bg-current" />
            {{ mode === 'real' ? 'Real' : 'Offline' }}
          </span>
        </div>
        <p class="mt-1.5 text-[13px] text-zinc-300">{{ t('app.version') }}</p>
      </div>
    </aside>

    <!-- Main column -->
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- TopBar: run context, wide -->
      <header class="flex h-14 shrink-0 items-center gap-4 border-b border-zinc-200 bg-white px-8">
        <div class="flex min-w-0 flex-1 items-center gap-3">
          <template v-if="store.current">
            <span class="inline-block h-2 w-2 shrink-0 rounded-full" :class="runStatusClass(runStatus)" />
            <span
              class="truncate text-[15px] font-medium text-zinc-800"
              :title="store.current.task"
            >
              {{ store.current.task }}
            </span>
            <span
              v-if="runStatus !== 'idle'"
              class="shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-medium"
              :class="statusPillClass(runStatus)"
            >
              {{ statusLabel(runStatus) }}
            </span>
          </template>
          <template v-else>
            <span class="text-[15px] text-zinc-400">{{ t('topbar.idle') }}</span>
          </template>
        </div>

        <div class="flex shrink-0 items-center gap-2.5">
          <span
            class="rounded-full border px-2.5 py-1 text-[12px] font-semibold"
            :class="mode === 'real' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-zinc-200 bg-zinc-50 text-zinc-500'"
            :title="t('app.mode_label')"
          >
            {{ mode === 'real' ? 'REAL' : 'OFFLINE' }}
          </span>
          <button
            type="button"
            class="rounded-md border border-zinc-200 px-2.5 py-1 text-[13px] text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-900"
            @click="toggleLocale"
          >
            {{ locale === 'zh' ? 'EN' : '中文' }}
          </button>
        </div>
      </header>

      <main class="min-h-0 flex-1 overflow-y-auto">
        <RouterView v-slot="{ Component }">
          <Transition name="view" mode="out-in">
            <!-- key by taskId so switching "recent" runs remounts the view -->
            <component :is="Component" :key="String(route.params.taskId ?? route.name ?? 'root')" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>