<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/i18n'

const route = useRoute()
const { t, toggleLocale } = useI18n()
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
          {{ t('app.name') }}
        </RouterLink>
        <nav v-if="taskId" class="flex items-center gap-1 text-sm">
          <RouterLink
            :to="{ name: 'execution', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
            exact-active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            {{ t('nav.overview') }}
          </RouterLink>
          <RouterLink
            :to="{ name: 'team', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            {{ t('nav.team') }}
          </RouterLink>
          <RouterLink
            :to="{ name: 'artifacts', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            {{ t('nav.artifacts') }}
          </RouterLink>
          <RouterLink
            :to="{ name: 'result', params: { taskId } }"
            class="rounded px-2.5 py-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            active-class="bg-zinc-100 font-medium text-zinc-900"
          >
            {{ t('nav.result') }}
          </RouterLink>
        </nav>
      </div>
      <div class="flex items-center gap-3">
        <button
          type="button"
          class="rounded border border-zinc-200 px-2 py-1 text-xs text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-900"
          @click="toggleLocale"
        >
          {{ t('nav.lang') }}
        </button>
        <span class="text-xs text-zinc-400">{{ t('app.version') }}</span>
      </div>
    </header>
    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>