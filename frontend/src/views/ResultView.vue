<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'
import { prettyJson } from '@/utils/format'
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
const insights = computed(() => result.value?.insights ?? [])
const contradictions = computed(() => result.value?.contradictions ?? [])
const uncertainties = computed(() => result.value?.uncertainties ?? [])
const tradeoffs = computed(() => result.value?.tradeoffs ?? [])
const recommendations = computed(() => result.value?.recommendations ?? [])
const hasSynthesis = computed(
  () =>
    insights.value.length > 0 ||
    contradictions.value.length > 0 ||
    uncertainties.value.length > 0 ||
    tradeoffs.value.length > 0 ||
    recommendations.value.length > 0,
)

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
  <div class="mx-auto w-full max-w-[1400px] px-10 py-10">
    <!-- Reader header -->
    <div v-if="result" class="mb-8 flex flex-wrap items-end justify-between gap-6">
      <div class="min-w-0 max-w-[840px]">
        <p class="tok-eyebrow mb-2">{{ t('result.deliverable') }}</p>
        <h1 class="line-clamp-2 text-[20px] font-semibold leading-snug tracking-tight text-zinc-900" :title="result.title">{{ result.title }}</h1>
        <div class="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[14px] text-zinc-400">
          <span class="inline-flex items-center gap-1.5">
            <span
              class="inline-block h-2 w-2 rounded-full bg-current"
              :class="mode() === 'real' ? 'text-emerald-500' : 'text-zinc-300'"
            />
            {{ mode() === 'real' ? 'Real' : 'Offline' }}
          </span>
          <span>{{ toc.length }} {{ t('result.sections') }}</span>
          <span>{{ sourcesCount }} {{ t('result.sources') }}</span>
          <span>{{ evidenceCount }} {{ t('result.evidence') }}</span>
        </div>
      </div>
      <div class="flex shrink-0 gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 px-3.5 py-2 text-[13px] font-medium text-zinc-600 transition-colors hover:bg-zinc-50"
          @click="copyMarkdown"
        >
          <UnitIcon name="copy" :size="14" />
          {{ copied ? t('result.copied') : t('result.copy') }}
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3.5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-blue-700"
          @click="downloadMarkdown"
        >
          <UnitIcon name="download" :size="14" />
          {{ t('result.save') }}
        </button>
      </div>
    </div>

    <p v-if="error" class="text-[15px] text-red-600">{{ error }}</p>
    <p v-else-if="!result" class="py-20 text-center text-[15px] text-zinc-400">
      {{ t('result.not_ready') }}
    </p>

    <div v-else class="grid grid-cols-12 gap-10">
      <!-- CONTENTS rail -->
      <nav class="col-span-3">
        <div class="sticky top-6">
          <p class="tok-eyebrow mb-3">{{ t('result.contents') }}</p>
          <ul class="border-l border-zinc-200">
            <li v-for="(section, idx) in toc" :key="idx">
              <button
                type="button"
                class="block w-full border-l-2 py-2 pl-4 text-left transition-colors"
                :class="activeSection === idx
                  ? '-ml-px border-blue-600 font-medium text-zinc-900'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800'"
                :title="splitSection(section).title"
                @click="selectSection(idx)"
              >
                <span class="font-mono text-[12px] text-zinc-300">{{ String(idx + 1).padStart(2, '0') }}</span>
                <span class="mt-0.5 block truncate text-[14px] leading-snug">{{ splitSection(section).title }}</span>
              </button>
            </li>
          </ul>
          <div class="mt-6 border-t border-zinc-200 pt-4 text-[13px] text-zinc-400">
            <p>{{ result.sources.length }} {{ t('result.sources') }} · {{ result.evidence.length }} {{ t('result.evidence') }}</p>
          </div>
        </div>
      </nav>

      <!-- Document body (reader) -->
      <div class="col-span-9 max-w-[880px]">
        <div class="space-y-8">
          <!-- Sections -->
          <section v-for="(section, idx) in toc" :key="idx" :id="`sec-${idx}`" class="scroll-mt-16">
            <div class="mb-2 flex items-baseline gap-3">
              <span class="font-mono text-[12px] text-zinc-300">{{ String(idx + 1).padStart(2, '0') }}</span>
              <h2 class="text-[16px] font-semibold tracking-tight text-zinc-900">
                {{ splitSection(section).title }}
              </h2>
            </div>
            <p class="mb-3 pl-7 text-[12px] text-zinc-400">
              {{ section.agent_name }} · {{ section.output_type }}
            </p>
            <div class="md-doc pl-7" v-html="section.content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')"></div>
            <!-- structured data: collapsed so long JSON never blocks the read -->
            <details v-if="Object.keys(section.structured_data).length" class="mt-4 rounded-lg border border-zinc-200 bg-zinc-50">
              <summary class="cursor-pointer select-none px-4 py-2.5 text-[12px] font-medium text-zinc-500 hover:text-zinc-800">
                Key data · {{ Object.keys(section.structured_data).length }} fields
              </summary>
              <pre class="max-h-56 overflow-auto border-t border-zinc-200 px-4 py-3 font-mono text-[12px] leading-relaxed text-zinc-600">{{
                prettyJson(section.structured_data)
              }}</pre>
            </details>
          </section>
        </div>

        <!-- v0.6 Synthesis blocks -->
        <section v-if="hasSynthesis" class="mt-10 border-t border-zinc-200 pt-6">
          <p class="tok-eyebrow mb-3">{{ t('result.synthesis') }}</p>
        </section>

        <section v-if="insights.length" class="mt-10 border-t border-zinc-200 pt-6">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.insights') }}
            <span class="ml-2 font-mono text-[12px] font-normal text-zinc-400">{{ insights.length }}</span>
          </h2>
          <ul class="space-y-3">
            <li v-for="item in insights" :key="item.insight_id" class="text-[13px]">
              <p class="text-zinc-800">{{ item.statement }}</p>
              <p class="mt-1 text-[12px] text-zinc-400">
                evidence: {{ (item.supporting_evidence_ids || []).join(', ') || '—' }}
                <template v-if="(item.producer_agents || []).length">
                  · agents: {{ item.producer_agents.join(', ') }}
                </template>
                <template v-if="item.uncertainty"> · {{ item.uncertainty }}</template>
              </p>
            </li>
          </ul>
        </section>

        <section v-if="contradictions.length || uncertainties.length" class="mt-10 border-t border-zinc-200 pt-6">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.contradictions') }}
          </h2>
          <ul class="space-y-3">
            <li v-for="item in contradictions" :key="item.contradiction_id" class="text-[13px]">
              <p class="text-zinc-800">
                <span class="font-mono text-[11px] text-zinc-400">[{{ item.status }}]</span>
                {{ item.claim_a }} ↔ {{ item.claim_b }}
              </p>
              <p class="mt-1 text-[12px] text-zinc-400">
                {{ item.resolution || 'Available evidence is insufficient to resolve the discrepancy.' }}
              </p>
            </li>
            <li v-for="item in uncertainties" :key="item.uncertainty_id" class="text-[13px]">
              <p class="text-zinc-800">
                <span class="font-mono text-[11px] text-zinc-400">({{ item.kind }})</span>
                {{ item.statement }}
              </p>
            </li>
          </ul>
        </section>

        <section v-if="tradeoffs.length" class="mt-10 border-t border-zinc-200 pt-6">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.tradeoffs') }}
            <span class="ml-2 font-mono text-[12px] font-normal text-zinc-400">{{ tradeoffs.length }}</span>
          </h2>
          <ul class="space-y-3">
            <li v-for="item in tradeoffs" :key="item.tradeoff_id" class="text-[13px]">
              <p class="font-medium text-zinc-800">{{ item.dimension }}</p>
              <p class="mt-1 text-[12px] text-zinc-500">
                A — {{ item.option_a || 'Option A' }}: + {{ (item.gains_a || []).join('; ') || '—' }} / − {{ (item.costs_a || []).join('; ') || '—' }}
              </p>
              <p class="mt-0.5 text-[12px] text-zinc-500">
                B — {{ item.option_b || 'Option B' }}: + {{ (item.gains_b || []).join('; ') || '—' }} / − {{ (item.costs_b || []).join('; ') || '—' }}
              </p>
              <p class="mt-1 text-[12px] text-zinc-400">
                evidence: {{ (item.evidence_ids || []).join(', ') || '—' }}
              </p>
            </li>
          </ul>
        </section>

        <section v-if="recommendations.length" class="mt-10 border-t border-zinc-200 pt-6">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.recommendations') }}
            <span class="ml-2 font-mono text-[12px] font-normal text-zinc-400">{{ recommendations.length }}</span>
          </h2>
          <ul class="space-y-3">
            <li v-for="item in recommendations" :key="item.recommendation_id" class="text-[13px]">
              <p class="text-zinc-800">
                <span class="font-mono text-[11px] text-zinc-400">[{{ item.status }}]</span>
                {{ item.statement }}
              </p>
              <p class="mt-1 text-[12px] text-zinc-400">
                insights: {{ (item.supporting_insight_ids || []).join(', ') || '—' }}
                · trade-offs: {{ (item.supporting_tradeoff_ids || []).join(', ') || '—' }}
                · evidence: {{ (item.supporting_evidence_ids || []).join(', ') || '—' }}
              </p>
              <p v-if="(item.limitations || []).length" class="mt-0.5 text-[12px] text-zinc-400">
                limitations: {{ item.limitations.join('; ') }}
              </p>
            </li>
          </ul>
        </section>

        <!-- Sources -->
        <section class="mt-10 border-t border-zinc-200 pt-6">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.sources') }}
            <span class="ml-2 font-mono text-[12px] font-normal text-zinc-400">{{ sourcesCount }}</span>
          </h2>
          <ol v-if="result.sources.length" class="space-y-2">
            <li v-for="(source, i) in result.sources" :key="source.id" class="flex gap-3">
              <span class="font-mono text-[11px] text-zinc-300">{{ String(i + 1).padStart(2, '0') }}</span>
              <div class="min-w-0 text-[13px]">
                <p class="text-zinc-700">{{ source.title }}</p>
                <p class="mt-0.5 text-[12px] text-zinc-400">
                  <a
                    v-if="source.url"
                    :href="source.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-blue-600 underline underline-offset-2 hover:text-blue-700"
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
        <section class="mt-10">
          <h2 class="mb-3 text-[15px] font-semibold tracking-tight text-zinc-900">
            {{ t('result.evidence') }}
            <span class="ml-2 font-mono text-[12px] font-normal text-zinc-400">{{ evidenceCount }}</span>
          </h2>
          <ul v-if="result.evidence.length" class="space-y-3">
            <li v-for="(ev, i) in result.evidence" :key="i" class="text-[13px]">
              <p class="text-zinc-700">
                <span class="font-mono text-[11px] text-zinc-300">#{{ i + 1 }}</span> {{ ev.claim }}
                <span class="font-mono text-[11px] text-zinc-300">→ {{ ev.source_id }}</span>
              </p>
              <p class="mt-1 pl-5 text-[12px] text-zinc-400">{{ ev.evidence }}</p>
            </li>
          </ul>
          <p v-else class="text-[13px] text-zinc-400">{{ t('result.no_evidence') }}</p>
        </section>
      </div>
    </div>
  </div>
</template>