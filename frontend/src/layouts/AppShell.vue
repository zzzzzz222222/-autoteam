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
const phase = computed(() => {
  const name = String(route.name ?? '')
  if (name === 'workspace') return 'workspace'
  if (name === 'execution') return 'execution'
  return name // team | artifacts | result
})

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

const runStatus = computed(() => store.current?.status ?? 'idle')
const mode = computed(() => store.current?.mode ?? 'offline')
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <!-- Sidebar -->
    <aside class="hidden w-52 shrink-0 flex-col border-r border-zinc-200 bg-white md:flex">
      <RouterLink to="/" class="flex items-center gap-2 px-5 py-5">
        <span class="flex h-6 w-6 items-center justify-center rounded-[4px] bg-zinc-900 text-[11px] font-bold text-white">
          A
        </span>
        <span class="text-sm font-semibold tracking-tight">AutoTeam</span>
      </RouterLink>

      <nav class="flex-1 space-y-0.5 px-3">
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          class="group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-zinc-500 transition-colors"
          :class="[
            item.active ? 'bg-zinc-100 font-medium text-zinc-900' : 'hover:bg-zinc-50 hover:text-zinc-800',
            item.disabled ? 'pointer-events-none opacity-40' : '',
          ]"
        >
          <UnitIcon :name="(item.icon as never)" :size="15" />
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="border-t border-zinc-100 px-5 py-4">
        <div class="flex items-center justify-between text-[11px]">
          <span class="text-zinc-400">{{ t('app.mode_label') }}</span>
          <span
            class="inline-flex items-center gap-1.5 font-medium"
            :class="mode === 'real' ? 'text-emerald-600' : 'text-zinc-500'"
          >
            <span class="inline-block h-1.5 w-1.5 rounded-full bg-current" />
            {{ mode === 'real' ? 'Real' : 'Offline' }}
          </span>
        </div>
        <p class="mt-1 text-[11px] text-zinc-300">{{ t('app.version') }}</p>
      </div>
    </aside>

    <!-- Main column -->
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- TopBar (run context) -->
      <header class="flex h-12 shrink-0 items-center gap-4 border-b border-zinc-200 bg-white px-6">
        <div class="flex min-w-0 flex-1 items-center gap-3">
          <template v-if="store.current">
            <span
              class="inline-block h-2 w-2 shrink-0 rounded-full"
              :class="runStatusClass(runStatus)"
            />
            <span class="truncate text-[13px] font-medium text-zinc-800">
              {{ store.current.task }}
            </span>
            <span v-if="runStatus !== 'idle'" class="shrink-0 text-[11px] text-zinc-400">
              {{ runStatus }}
            </span>
          </template>
          <template v-else>
            <span class="text-[13px] text-zinc-400">{{ t('topbar.idle') }}</span>
          </template>
        </div>

        <div class="flex shrink-0 items-center gap-2">
          <span
            class="rounded-full border px-2 py-0.5 text-[11px] font-medium"
            :class="mode === 'real' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-zinc-200 bg-zinc-50 text-zinc-500'"
          >
            {{ mode === 'real' ? 'REAL' : 'OFFLINE' }}
          </span>
          <button
            type="button"
            class="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-900"
            @click="toggleLocale"
          >
            {{ locale === 'zh' ? 'EN' : '中文' }}
          </button>
        </div>
      </header>

      <main class="min-h-0 flex-1 overflow-y-auto">
        <RouterView v-slot="{ Component }">
          <Transition name="view" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<script lang="ts">
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
</script>