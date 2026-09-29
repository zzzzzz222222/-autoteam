<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'
import type { FinalResultResponse, SectionDto } from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const result = ref<FinalResultResponse | null>(null)
const error = ref<string | null>(null)
const copied = ref(false)
const activeSection = ref(0)

async function load() {
  try {
    result.value = await api.getResult(props.taskId)
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

const toc = computed(() => result.value?.sections ?? [])

const sourcesCount = computed(() => result.value?.sources.length ?? 0)
const evidenceCount = computed(() => result.value?.evidence.length ?? 0)

function mode(): 'real' | 'offline' {
  return store.current?.mode === 'real' ? 'real' : 'offline'
}

async function copyMarkdown() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.markdown)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* clipboard unavailable */
  }
}

function downloadMarkdown() {
  if (!result.value) return
  const blob = new Blob([result.value.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.taskId}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function selectSection(index: number) {
  activeSection.value = index
  document.getElementById(`sec-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function splitSection(section: SectionDto): { title: string } {
  const lines = section.content.split('\n')
  const title = lines.find((l) => l.trim().startsWith('**'))?.replace(/\*\*/g, '')?.trim() || section.title
  return { title }
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-8 py-8">
    <p class="tok-eyebrow mb-2">{{ t('result.deliverable') }}</p>

    <!-- Header: title + actions + meta -->
    <div v-if="result" class="mb-6 flex items-end justify-between gap-6">
      <div class="min-w-0">
        <h1 class="truncate text-2xl font-semibold tracking-tight text-zinc-900">
          {{ result.title }}
        </h1>
        <div class="mt-2 flex items-center gap-4 text-[11px] text-zinc-400">
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-1.5 w-1.5 rounded-full bg-current" :class="mode() === 'real' ? 'text-emerald-500' : 'text-zinc-300'" />
            {{ mode() === 'real' ? 'Real' : 'Offline' }}
          </span>
          <span>{{ toc.length }} sections</span>
          <span>{{ sourcesCount }} sources</span>
          <span>{{ evidenceCount }} evidence</span>
        </div>
      </div>
      <div class="flex shrink-0 gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 px-3 py-1.5 text-[12px] font-medium text-zinc-600 transition-colors hover:bg-zinc-50"
          @click="copyMarkdown"
        >
          <UnitIcon name="copy" :size="13" />
          {{ copied ? t('result.copied') : t('result.copy') }}
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-zinc-700"
          @click="downloadMarkdown"
        >
          <UnitIcon name="download" :size="13" />
          {{ t('result.save') }}
        </button>
      </div>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="!result" class="py-16 text-center text-sm text-zinc-400">
      {{ t('result.not_ready') }}
    </p>

    <div v-else class="grid grid-cols-12 gap-10">
      <!-- CONTENTS rail -->
      <nav class="col-span-3">
        <div class="sticky top-6">
          <p class="tok-eyebrow mb-3">{{ t('result.contents') }}</p>
          <ul class="space-y-0.5">
            <li v-for="(section, idx) in toc" :key="idx">
              <button
                type="button"
                class="w-full rounded px-2 py-1.5 text-left text-[13px] transition-colors"
                :class="activeSection === idx ? 'bg-zinc-100 font-medium text-zinc-900' : 'text-zinc-500 hover:text-zinc-800'"
                @click="selectSection(idx)"
              >
                {{ splitSection(section).title }}
              </button>
            </li>
          </ul>
          <div class="mt-6 border-t border-zinc-200 pt-3 text-[11px] text-zinc-400">
            <p>{{ result.sources.length }} {{ t('result.sources') }}</p>
            <p>{{ result.evidence.length }} {{ t('result.evidence') }}</p>
          </div>
        </div>
      </nav>

      <!-- Document body -->
      <div class="col-span-9 space-y-8">
        <!-- Sections -->
        <section v-for="(section, idx) in toc" :key="idx" :id="`sec-${idx}`" class="scroll-mt-20 border-b border-zinc-200 pb-8">
          <div class="mb-2 flex items-baseline gap-3">
            <span class="font-mono text-[11px] text-zinc-300">{{ String(idx + 1).padStart(2, '0') }}</span>
            <h2 class="text-[16px] font-semibold tracking-tight text-zinc-900">
              {{ splitSection(section).title }}
            </h2>
          </div>
          <p class="mb-4 text-[12px] text-zinc-400">
            {{ section.agent_name }} · {{ section.output_type }}
          </p>
          <div class="md-doc" v-html="section.content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')"></div>
          <div v-if="Object.keys(section.structured_data).length" class="mt-4 rounded bg-zinc-50 p-3">
            <pre class="overflow-x-auto font-mono text-[11px] leading-relaxed text-zinc-500">{{
              JSON.stringify(section.structured_data, null, 2)
            }}</pre>
          </div>
        </section>

        <!-- Sources -->
        <section class="border-b border-zinc-200 pb-8">
          <h2 class="mb-4 text-[16px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.sources') }}
            <span class="ml-2 font-mono text-[11px] font-normal text-zinc-400">
              {{ sourcesCount }}
            </span>
          </h2>
          <ol v-if="result.sources.length" class="space-y-2.5">
            <li v-for="(source, i) in result.sources" :key="source.id" class="flex gap-3">
              <span class="font-mono text-[11px] text-zinc-300">{{ String(i + 1).padStart(2, '0') }}</span>
              <div class="min-w-0 text-[13px]">
                <p class="text-zinc-700">{{ source.title }}</p>
                <p class="text-[11px] text-zinc-400">
                  <a
                    v-if="source.url"
                    :href="source.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="underline underline-offset-2 hover:text-zinc-700"
                  >
                    {{ source.url }}
                  </a>
                  <span v-else>{{ t('result.offline_source') }}</span>
                </p>
              </div>
            </li>
          </ol>
          <p v-else class="text-[13px] text-zinc-400">{{ t('result.no_sources') }}</p>
        </section>

        <!-- Evidence -->
        <section>
          <h2 class="mb-4 text-[16px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.evidence') }}
            <span class="ml-2 font-mono text-[11px] font-normal text-zinc-400">
              {{ evidenceCount }}
            </span>
          </h2>
          <ul v-if="result.evidence.length" class="space-y-3">
            <li v-for="(ev, i) in result.evidence" :key="i" class="text-[13px]">
              <p class="text-zinc-700">
                <span class="font-mono text-[10px] text-zinc-300">#{{ i + 1 }}</span> {{ ev.claim }}
                <span class="text-zinc-300">→ {{ ev.source_id }}</span>
              </p>
              <p class="mt-0.5 pl-5 text-[12px] text-zinc-400">{{ ev.evidence }}</p>
            </li>
          </ul>
          <p v-else class="text-[13px] text-zinc-400">{{ t('result.no_evidence') }}</p>
        </section>
      </div>
    </div>
  </div>
</template>