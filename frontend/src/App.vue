<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const taskId = computed(() => (route.params.taskId as string) ?? '')
</script>

<template>
  <div class="flex h-full min-h-screen flex-col">
    <header
      class="flex h-12 shrink-0 items-center justify-between border-b border-zinc-200 bg-white px-6"
    >
      <div class="flex items-center gap-6">
        <RouterLink to="/" class="flex items-center gap-2 font-semibold tracking-tight">
          <span
            class="inline-flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-[11px] font-bold text-white"
            >A</span
          >
          AutoTeam
        </RouterLink>
        <nav v-if="taskId" class="flex items-center gap-1 text-sm">
          <RouterLink
            :to="{ name: 'execution', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
            exact-active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            Overview
          </RouterLink>
          <RouterLink
            :to="{ name: 'team', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            Team
          </RouterLink>
          <RouterLink
            :to="{ name: 'artifacts', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            Artifacts
          </RouterLink>
          <RouterLink
            :to="{ name: 'result', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            Result
          </RouterLink>
        </nav>
      </div>
      <span class="text-xs text-zinc-400">v0.5.0</span>
    </header>
    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>