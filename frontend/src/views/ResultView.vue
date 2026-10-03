<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useI18n } from '@/i18n'
import UnitIcon from '@/components/UnitIcon.vue'
import RefChip from '@/components/RefChip.vue'
import { hostOf, prettyJson, safeHttpUrl, truncateMiddle } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import type {
  EvidenceDto,
  FinalResultResponse,
  InsightDto,
  RecommendationDto,
  SectionDto,
  SourceDto,
  TradeoffDto,
} from '@/types'

const props = defineProps<{ taskId: string }>()
const store = useTeamStore()
const { t } = useI18n()

const result = ref<FinalResultResponse | null>(null)
const error = ref<string | null>(null)
const copied = ref(false)
const activeAnchor = ref('')

async function load() {
  try {
    result.value = await api.getResult(props.taskId)
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

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

// ---------------------------------------------------------------------------
// Data views (read-only projections of the real backend payload)
// ---------------------------------------------------------------------------
const sourcesCount = computed(() => result.value?.sources.length ?? 0)
const evidenceCount = computed(() => result.value?.evidence.length ?? 0)
const findings = computed(() => result.value?.findings ?? [])
const insights = computed(() => result.value?.insights ?? [])
const contradictions = computed(() => result.value?.contradictions ?? [])
const uncertainties = computed(() => result.value?.uncertainties ?? [])
const tradeoffs = computed(() => result.value?.tradeoffs ?? [])
const recommendations = computed(() => result.value?.recommendations ?? [])
const referenceIssues = computed(() => result.value?.reference_issues ?? [])
const synthesisStatus = computed(() => result.value?.synthesis_status || '')
const degraded = computed(() => synthesisStatus.value === 'degraded' || synthesisStatus.value === 'failed')

const SYNTHESIS_TYPES = new Set(['findings', 'insights', 'contradictions', 'tradeoffs', 'recommendations'])
const agentSections = computed<SectionDto[]>(() =>
  (result.value?.sections ?? []).filter((s) => !SYNTHESIS_TYPES.has(s.output_type)),
)

const sourcesById = computed(() => {
  const map = new Map<string, SourceDto>()
  for (const source of result.value?.sources ?? []) map.set(source.id, source)
  return map
})
const evidenceById = computed(() => {
  const map = new Map<string, EvidenceDto>()
  ;(result.value?.evidence ?? []).forEach((item, index) => {
    map.set(item.evidence_id || `__index_${index}`, item)
  })
  return map
})

function evidence(id: string): EvidenceDto | null {
  return evidenceById.value.get(id) ?? null
}
function insight(id: string): InsightDto | null {
  return insights.value.find((item) => item.insight_id === id) ?? null
}
function tradeoff(id: string): TradeoffDto | null {
  return tradeoffs.value.find((item) => item.tradeoff_id === id) ?? null
}
function distinctSources(evidenceIds: string[]): string[] {
  const set = new Set<string>()
  for (const id of evidenceIds) {
    const item = evidence(id)
    if (item?.source_id) set.add(item.source_id)
  }
  return [...set].sort()
}

const evidenceUsage = computed(() => {
  const usage = new Map<string, { findings: string[]; insights: string[]; tradeoffs: string[]; recommendations: string[] }>()
  const ensure = (id: string) => {
    if (!usage.has(id)) usage.set(id, { findings: [], insights: [], tradeoffs: [], recommendations: [] })
    return usage.get(id)!
  }
  for (const item of findings.value) for (const id of item.evidence_ids) ensure(id).findings.push(item.finding_id)
  for (const item of insights.value) for (const id of item.supporting_evidence_ids) ensure(id).insights.push(item.insight_id)
  for (const item of tradeoffs.value) for (const id of item.evidence_ids) ensure(id).tradeoffs.push(item.tradeoff_id)
  for (const item of recommendations.value) for (const id of item.supporting_evidence_ids) ensure(id).recommendations.push(item.recommendation_id)
  return usage
})
function usedBy(id: string): string[] {
  const entry = evidenceUsage.value.get(id)
  if (!entry) return []
  const labels: string[] = []
  if (entry.findings.length) labels.push(`${t('result.key_findings')}: ${entry.findings.join(', ')}`)
  if (entry.insights.length) labels.push(`${t('result.insights')}: ${entry.insights.join(', ')}`)
  if (entry.tradeoffs.length) labels.push(`${t('result.tradeoffs')}: ${entry.tradeoffs.join(', ')}`)
  if (entry.recommendations.length) labels.push(`${t('result.recommendations')}: ${entry.recommendations.join(', ')}`)
  return labels
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------
function supportKey(kind: string): string {
  if (kind === 'multi_source') return 'result.support.multi_source'
  if (kind === 'single_source') return 'result.support.single_source'
  // v0.6.6: agent agreement is no longer rendered as multi-source support.
  if (kind === 'multi_agent') return 'result.support.multi_agent'
  if (kind === 'agent_restatement') return 'result.support.agent_restatement'
  if (kind === 'conflict') return 'result.support.conflict'
  return 'result.support.unsupported'
}
function supportClass(kind: string): string {
  if (kind === 'multi_source') return 'at-chip--info'
  if (kind === 'single_source') return 'at-chip--neutral'
  if (kind === 'multi_agent') return 'at-chip--neutral'
  if (kind === 'agent_restatement') return 'at-chip--warn'
  if (kind === 'conflict') return 'at-chip--warn'
  return 'at-chip--warn'
}
function supportLevelKey(level: string): string {
  return 'result.level.' + (level || 'unknown')
}
function supportLevelClass(level: string): string {
  if (level === 'source_text') return 'at-chip--info'
  if (level === 'derived') return 'at-chip--neutral'
  if (level === 'planning_assumption') return 'at-chip--neutral'
  return 'at-chip--warn'
}
function citationClass(status: string): string {
  if (status === 'unsupported' || status === 'source_unavailable') return 'at-chip--warn'
  return 'at-chip--neutral'
}
const NATURE_KEYS: Record<string, string> = {
  source_fact: 'result.nature.source_fact',
  derived_estimate: 'result.nature.derived_estimate',
  planning_assumption: 'result.nature.planning_assumption',
  unverified_claim: 'result.nature.unverified_claim',
}
function hasNature(claimType?: string): boolean {
  return !!claimType && claimType in NATURE_KEYS
}
function natureKey(claimType?: string): string {
  return (claimType && NATURE_KEYS[claimType]) || 'result.nature.unclassified'
}
function natureClass(claimType?: string): string {
  switch (claimType) {
    case 'source_fact':
      return 'at-chip--info'
    case 'derived_estimate':
      return 'at-chip--neutral'
    case 'planning_assumption':
      return 'at-chip--brand'
    case 'unverified_claim':
      return 'at-chip--warn'
    default:
      return 'at-chip--neutral'
  }
}
function recStatusKey(status: string): string {
  if (status === 'supported') return 'result.rec.supported'
  if (status === 'potential') return 'result.rec.potential'
  return 'result.rec.unsupported'
}
function recStatusClass(status: string): string {
  if (status === 'supported') return 'at-chip--info'
  if (status === 'potential') return 'at-chip--neutral'
  return 'at-chip--warn'
}
function crossAgent(agents: string[]): boolean {
  return agents.length >= 2
}
function clip(text: string, limit = 90): string {
  const clean = (text || '').replace(/\s+/g, ' ').trim()
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean
}
function sectionTitle(section: SectionDto): string {
  const line = section.content.split('\n').find((l) => l.trim().startsWith('**'))
  return line?.replace(/\*\*/g, '')?.trim() || section.title
}

// ---------------------------------------------------------------------------
// M5 - provenance tree (Recommendation -> Insight/Trade-off -> Evidence -> Source)
// Built strictly from the backend's real reference ids; missing ids resolve to
// an honest "reference missing" node instead of a fabricated anchor.
// ---------------------------------------------------------------------------
type TraceKind = 'insight' | 'tradeoff' | 'evidence' | 'source'

interface TraceNode {
  key: string
  kind: TraceKind
  id: string
  label: string
  resolved: boolean
  target: string | null
  children: TraceNode[]
}

function anchor(kind: TraceKind, id: string): string {
  return `${kind}-${id}`
}

function sourceNode(sourceId: string, prefix: string): TraceNode {
  const source = sourcesById.value.get(sourceId)
  return {
    key: `${prefix}/src:${sourceId}`,
    kind: 'source',
    id: sourceId,
    label: source ? source.title || hostOf(source.url) || sourceId : sourceId,
    resolved: !!source,
    target: source ? anchor('source', sourceId) : null,
    children: [],
  }
}

function evidenceNode(id: string, prefix: string): TraceNode {
  const item = evidence(id)
  const resolved = !!item
  const children = resolved && item?.source_id ? [sourceNode(item.source_id, `${prefix}/ev:${id}`)] : []
  return {
    key: `${prefix}/ev:${id}`,
    kind: 'evidence',
    id,
    label: item ? clip(item.claim, 54) : t('result.locate_missing', { id }),
    resolved,
    target: resolved ? anchor('evidence', id) : null,
    children,
  }
}

function insightNode(id: string): TraceNode {
  const item = insight(id)
  const resolved = !!item
  const children = resolved
    ? (item?.supporting_evidence_ids ?? []).map((eid) => evidenceNode(eid, `rec/ins:${id}`))
    : []
  return {
    key: `rec/ins:${id}`,
    kind: 'insight',
    id,
    label: item ? clip(item.statement, 54) : t('result.locate_missing', { id }),
    resolved,
    target: resolved ? anchor('insight', id) : null,
    children,
  }
}

function tradeoffNode(id: string): TraceNode {
  const item = tradeoff(id)
  const resolved = !!item
  const children = resolved ? (item?.evidence_ids ?? []).map((eid) => evidenceNode(eid, `rec/trd:${id}`)) : []
  return {
    key: `rec/trd:${id}`,
    kind: 'tradeoff',
    id,
    label: item ? clip(item.dimension, 54) : t('result.locate_missing', { id }),
    resolved,
    target: resolved ? anchor('tradeoff', id) : null,
    children,
  }
}

function recTrace(rec: RecommendationDto): TraceNode[] {
  const nodes: TraceNode[] = []
  for (const id of rec.supporting_insight_ids) nodes.push(insightNode(id))
  for (const id of rec.supporting_tradeoff_ids) nodes.push(tradeoffNode(id))
  for (const id of rec.supporting_evidence_ids) nodes.push(evidenceNode(id, 'rec/direct'))
  return nodes
}

function evidenceTarget(id: string): string | null {
  return evidence(id) ? anchor('evidence', id) : null
}

const highlightedId = ref('')
let highlightTimer: number | null = null
function locate(target: string | null) {
  if (!target) return
  const el = document.getElementById(target)
  if (!el) return
  const reduce =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' })
  highlightedId.value = target
  if (highlightTimer) window.clearTimeout(highlightTimer)
  highlightTimer = window.setTimeout(() => (highlightedId.value = ''), 1900) as unknown as number
}
function isHighlighted(target: string): boolean {
  return highlightedId.value === target
}

// ---------------------------------------------------------------------------
// Contents navigation
// ---------------------------------------------------------------------------
interface TocItem {
  id: string
  label: string
  count: number
}
const toc = computed<TocItem[]>(() => {
  const items: TocItem[] = []
  if (findings.value.length) items.push({ id: 'block-findings', label: t('result.key_findings'), count: findings.value.length })
  if (insights.value.length) items.push({ id: 'block-insights', label: t('result.insights'), count: insights.value.length })
  if (contradictions.value.length || uncertainties.value.length)
    items.push({ id: 'block-contradictions', label: t('result.contradictions'), count: contradictions.value.length + uncertainties.value.length })
  if (tradeoffs.value.length) items.push({ id: 'block-tradeoffs', label: t('result.tradeoffs'), count: tradeoffs.value.length })
  if (recommendations.value.length) items.push({ id: 'block-recommendations', label: t('result.recommendations'), count: recommendations.value.length })
  agentSections.value.forEach((section, index) => items.push({ id: `sec-${index}`, label: sectionTitle(section), count: 0 }))
  items.push({ id: 'block-evidence', label: t('result.evidence'), count: evidenceCount.value })
  items.push({ id: 'block-sources', label: t('result.sources'), count: sourcesCount.value })
  return items
})

const showToc = computed(() => toc.value.length >= 4)

function scrollTo(id: string) {
  activeAnchor.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function href(url?: string): string | null {
  return safeHttpUrl(url)
}
function shortUrl(url?: string): string {
  return truncateMiddle(url ?? '', 68)
}
function sourceLabel(source: SourceDto): string {
  return source.title || hostOf(source.url) || source.id
}
function contradictionStatusKey(status: string): string {
  return status === 'resolved' ? 'result.resolved' : 'result.unresolved'
}
function contradictionStatusClass(status: string): string {
  return status === 'resolved' ? 'at-chip--info' : 'at-chip--warn'
}

const SYNTH_KEYS: Record<string, string> = {
  completed: 'result.synth.completed',
  degraded: 'result.synth.degraded',
  failed: 'result.synth.failed',
}
function synthKey(s: string): string {
  return SYNTH_KEYS[s] ?? s
}
const CHAIN_KEYS: Record<string, string> = {
  insight: 'chain.insight',
  tradeoff: 'chain.tradeoff',
  evidence: 'chain.evidence',
  source: 'chain.source',
}
function chainKey(k: string): string {
  return CHAIN_KEYS[k] ?? k
}
const UNC_KEYS: Record<string, string> = {
  insufficient_evidence: 'result.unc.kind.insufficient_evidence',
  single_source: 'result.unc.kind.single_source',
  conflicting: 'result.unc.kind.conflicting',
  vague: 'result.unc.kind.vague',
}
function uncKey(k: string): string {
  return UNC_KEYS[k] ?? k
}
</script>

<template>
  <div class="mx-auto w-full max-w-[1400px] px-6 py-8 md:px-10 md:py-10">
    <!-- Reader header -->
    <header v-if="result" class="mb-8 flex flex-wrap items-end justify-between gap-6">
      <div class="min-w-0 max-w-[840px]">
        <p class="at-eyebrow mb-2">{{ t('result.deliverable') }}</p>
        <h1 class="line-clamp-2 at-t-xl font-semibold leading-snug at-fg" :title="result.title">{{ result.title }}</h1>
        <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 at-t-xs">
          <span class="at-chip">
            <span
              class="at-dot"
              :class="mode() === 'real' ? 'at-dot--real' : 'at-dot--offline'"
              style="width: 6px; height: 6px"
              aria-hidden="true"
            />
            {{ t(mode() === 'real' ? 'mode.real' : 'mode.offline') }}
          </span>
          <span class="at-dim">{{ agentSections.length }} {{ t('result.sections') }}</span>
          <span class="at-dim">{{ sourcesCount }} {{ t('result.sources') }}</span>
          <span class="at-dim">{{ evidenceCount }} {{ t('result.evidence') }}</span>
          <span
            v-if="synthesisStatus && synthesisStatus !== 'completed'"
            class="at-chip"
            :class="degraded ? 'at-chip--warn' : ''"
          >
            {{ t('result.synthesis') }}: {{ t(synthKey(synthesisStatus)) }}
          </span>
        </div>
      </div>
      <div class="flex shrink-0 gap-2">
        <button type="button" class="at-btn at-btn-ghost" @click="copyMarkdown">
          <UnitIcon name="copy" :size="14" />
          {{ copied ? t('result.copied') : t('result.copy') }}
        </button>
        <button type="button" class="at-btn at-btn-primary" @click="downloadMarkdown">
          <UnitIcon name="download" :size="14" />
          {{ t('result.save') }}
        </button>
      </div>
    </header>

    <p v-if="error" role="alert" class="at-t-base at-danger-text">{{ error }} <span class="at-t-xs at-muted">{{ t('common.error_reload_hint') }}</span></p>
    <div v-else-if="!result" class="mx-auto max-w-md space-y-3 py-20">
      <div class="at-skeleton h-4 w-40"></div>
      <div class="at-skeleton h-3 w-full"></div>
      <p class="text-center at-t-base at-dim">{{ t('result.not_ready') }}</p>
    </div>

    <div v-else class="grid grid-cols-12 gap-8 lg:gap-10">
      <!-- CONTENTS rail -->
      <nav v-if="showToc" class="col-span-12 lg:col-span-3" :aria-label="t('result.contents')">
        <div class="lg:sticky lg:top-6">
          <p class="at-eyebrow mb-3">{{ t('result.contents') }}</p>
          <ul class="space-y-0.5 border-l at-border">
            <li v-for="item in toc" :key="item.id">
              <button
                type="button"
                class="flex w-full items-baseline gap-2 border-l-2 py-1.5 pl-3 text-left transition-colors"
                :class="activeAnchor === item.id
                  ? '-ml-px border-[var(--at-accent)] font-medium at-fg'
                  : 'border-transparent at-muted hover:at-fg'"
                :title="item.label"
                @click="scrollTo(item.id)"
              >
                <span class="min-w-0 flex-1 truncate at-t-sm leading-snug">{{ item.label }}</span>
                <span v-if="item.count" class="shrink-0 font-mono at-t-xs at-dim at-num">{{ item.count }}</span>
              </button>
            </li>
          </ul>
          <div class="mt-6 border-t at-border pt-4 font-mono at-t-xs at-dim">
            <p>{{ sourcesCount }} {{ t('result.sources') }} · {{ evidenceCount }} {{ t('result.evidence') }}</p>
          </div>
        </div>
      </nav>

      <!-- Document body -->
      <div class="col-span-12 min-w-0 space-y-8" :class="showToc ? 'lg:col-span-9' : ''">
        <!-- Degraded notice -->
        <div v-if="degraded" class="at-card flex gap-3 border-l-2 p-4" style="border-left-color: var(--at-warn)">
          <UnitIcon name="alertTriangle" :size="17" class="mt-0.5 shrink-0 at-warn-text" />
          <div class="min-w-0">
            <p class="at-t-sm font-medium at-warn-text">{{ t('result.synthesis_degraded') }}</p>
            <p v-if="result.synthesis_degradation_reason" class="mt-1 break-all font-mono at-t-xs at-dim">
              {{ result.synthesis_degradation_reason }}
            </p>
          </div>
        </div>

        <!-- Reference issues -->
        <details v-if="referenceIssues.length" class="at-card p-4">
          <summary class="cursor-pointer select-none at-t-xs font-medium at-dim">{{ t('result.ref_issues') }} · {{ referenceIssues.length }}</summary>
          <ul class="mt-2 list-disc space-y-1 pl-5 font-mono at-t-xs at-muted">
            <li v-for="issue in referenceIssues" :key="issue" class="break-all">{{ issue }}</li>
          </ul>
        </details>

        <!-- Key Findings -->
        <section v-if="findings.length" id="block-findings" class="scroll-mt-20">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.key_findings') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ findings.length }}</span>
          </h2>
          <ul class="at-list">
            <li v-for="item in findings" :key="item.finding_id" :id="'finding-' + item.finding_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('finding-' + item.finding_id) }">
              <p class="at-t-base leading-relaxed at-fg">{{ item.statement }}</p>
              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <span class="at-chip" :class="supportClass(item.support_kind)">{{ t(supportKey(item.support_kind)) }}</span>
                <span v-if="item.support_level" class="at-chip" :class="supportLevelClass(item.support_level)">
                  {{ t('result.support_level') }}: {{ t(supportLevelKey(item.support_level)) }}
                </span>
                <span v-if="hasNature(item.claim_type)" class="at-chip" :class="natureClass(item.claim_type)">
                  {{ t('result.data_nature') }}: {{ t(natureKey(item.claim_type)) }}
                </span>
                <span v-if="item.review_status" class="at-chip" :class="citationClass(item.review_status)">
                  {{ t('result.citation_check') }}: {{ item.review_status }}
                </span>
                <span class="at-t-xs at-dim at-num">
                  {{ item.evidence_count ?? item.evidence_ids.length }} {{ t('result.evidence_count') }}
                  · {{ item.independent_source_count ?? distinctSources(item.evidence_ids).length }} {{ t('result.source_count') }}
                  <template v-if="item.agent_support_count"> · {{ item.agent_support_count }} {{ t('result.supporting_agents') }}</template>
                </span>
                <span v-if="item.supporting_agents.length" class="at-t-xs at-dim">{{ t('result.supporting_agents') }}: {{ item.supporting_agents.join(', ') }}</span>
              </div>
              <details v-if="item.evidence_ids.length || item.derivation || item.finding_id" class="mt-3">
                <summary class="cursor-pointer select-none at-t-xs font-medium at-dim hover:at-fg">{{ t('result.details') }}</summary>
                <div class="mt-2 space-y-2 border-l at-border pl-3">
                  <div v-if="item.evidence_ids.length" class="flex flex-wrap items-center gap-1.5">
                    <RefChip v-for="id in item.evidence_ids" :key="id" :id="evidence(id)?.evidence_id || id" :resolved="!!evidence(id)" :clickable="!!evidence(id)" :target="evidenceTarget(id)" @select="locate" />
                  </div>
                  <p v-if="item.derivation" class="at-t-xs at-muted"><span class="at-dim">{{ t('result.derivation') }}:</span> {{ item.derivation }}</p>
                  <p class="font-mono at-t-xs at-dim">{{ item.finding_id }}</p>
                </div>
              </details>
            </li>
          </ul>
        </section>

        <!-- Insights -->
        <section v-if="insights.length" id="block-insights" class="scroll-mt-20">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.insights') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ insights.length }}</span>
          </h2>
          <ul class="at-list">
            <li v-for="item in insights" :key="item.insight_id" :id="'insight-' + item.insight_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('insight-' + item.insight_id) }">
              <p class="at-t-base leading-relaxed at-fg">{{ item.statement }}</p>
              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <span class="at-chip" :class="crossAgent(item.contributing_agents || item.producer_agents) ? 'at-chip--info' : 'at-chip--neutral'">
                  {{ crossAgent(item.contributing_agents || item.producer_agents) ? t('result.cross_agent') : t('result.single_agent') }}
                </span>
                <span v-if="hasNature(item.claim_type)" class="at-chip" :class="natureClass(item.claim_type)">
                  {{ t('result.data_nature') }}: {{ t(natureKey(item.claim_type)) }}
                </span>
                <span class="at-t-xs at-dim at-num">{{ item.supporting_evidence_ids.length }} {{ t('result.evidence_count') }} · {{ distinctSources(item.supporting_evidence_ids).length }} {{ t('result.source_count') }}</span>
                <span v-if="(item.contributing_agents || item.producer_agents).length" class="at-t-xs at-dim">{{ t('result.contributing_agents') }}: {{ (item.contributing_agents || item.producer_agents).join(', ') }}</span>
              </div>
              <p v-if="item.uncertainty" class="mt-1.5 at-t-xs at-warn-text">{{ t('result.applicability') }}: {{ item.uncertainty }}</p>
              <details v-if="item.supporting_evidence_ids.length || item.derivation" class="mt-3">
                <summary class="cursor-pointer select-none at-t-xs font-medium at-dim hover:at-fg">{{ t('result.details') }}</summary>
                <div class="mt-2 space-y-2 border-l at-border pl-3">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <RefChip v-for="id in item.supporting_evidence_ids" :key="id" :id="evidence(id)?.evidence_id || id" :resolved="!!evidence(id)" :clickable="!!evidence(id)" :target="evidenceTarget(id)" @select="locate" />
                  </div>
                  <p v-if="item.derivation" class="at-t-xs at-muted"><span class="at-dim">{{ t('result.how_combined') }}:</span> {{ item.derivation }}</p>
                  <p class="font-mono at-t-xs at-dim">{{ item.insight_id }}</p>
                </div>
              </details>
            </li>
          </ul>
        </section>

        <!-- Contradictions & Uncertainties -->
        <section v-if="contradictions.length || uncertainties.length" id="block-contradictions" class="scroll-mt-20">
          <h2 class="at-h2 mb-3">{{ t('result.contradictions') }}</h2>
          <ul class="at-list">
            <li v-for="item in contradictions" :key="item.contradiction_id" :id="'contradiction-' + item.contradiction_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('contradiction-' + item.contradiction_id) }">
              <div class="flex flex-wrap items-center gap-2">
                <span class="at-chip" :class="contradictionStatusClass(item.status)">{{ t(contradictionStatusKey(item.status)) }}</span>
                <span v-if="item.agents.length" class="at-t-xs at-dim">{{ t('result.supporting_agents') }}: {{ item.agents.join(', ') }}</span>
              </div>
              <div class="mt-2 space-y-1.5 at-t-sm leading-relaxed at-fg">
                <p><span class="at-dim">A ·</span> {{ item.claim_a }}</p>
                <p><span class="at-dim">B ·</span> {{ item.claim_b }}</p>
              </div>
              <p class="mt-2 at-t-xs at-muted"><span class="at-dim">{{ t('result.unresolved_reason') }}:</span> {{ item.resolution || 'Available evidence is insufficient to resolve the discrepancy.' }}</p>
              <div v-if="item.evidence_ids.length" class="mt-2 flex flex-wrap items-center gap-1.5">
                <RefChip v-for="id in item.evidence_ids" :key="id" :id="evidence(id)?.evidence_id || id" :resolved="!!evidence(id)" :clickable="!!evidence(id)" :target="evidenceTarget(id)" @select="locate" />
              </div>
            </li>
            <li v-for="item in uncertainties" :key="item.uncertainty_id" :id="'uncertainty-' + item.uncertainty_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('uncertainty-' + item.uncertainty_id) }">
              <span class="at-chip">{{ t('result.uncertainty_kind') }}: {{ t(uncKey(item.kind)) }}</span>
              <p class="mt-2 at-t-sm leading-relaxed at-fg">{{ item.statement }}</p>
              <p v-if="item.note" class="mt-1 at-t-xs at-muted">{{ t('result.impact') }}: {{ item.note }}</p>
              <div v-if="item.evidence_ids.length" class="mt-2 flex flex-wrap items-center gap-1.5">
                <RefChip v-for="id in item.evidence_ids" :key="id" :id="evidence(id)?.evidence_id || id" :resolved="!!evidence(id)" :clickable="!!evidence(id)" :target="evidenceTarget(id)" @select="locate" />
              </div>
            </li>
          </ul>
        </section>

        <!-- Trade-offs -->
        <section v-if="tradeoffs.length" id="block-tradeoffs" class="scroll-mt-20">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.tradeoffs') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ tradeoffs.length }}</span>
          </h2>
          <ul class="at-list">
            <li v-for="item in tradeoffs" :key="item.tradeoff_id" :id="'tradeoff-' + item.tradeoff_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('tradeoff-' + item.tradeoff_id) }">
              <p class="at-t-base font-semibold at-fg">{{ t('result.dimension') }}: {{ item.dimension }}</p>
              <div class="mt-3 grid gap-3 md:grid-cols-2">
                <div class="at-inset p-3">
                  <p class="at-t-sm font-medium at-fg">{{ t('result.option_a') }} · {{ item.option_a || 'A' }}</p>
                  <p class="mt-1 at-t-xs at-fg">+ {{ (item.gains_a || []).join('; ') || '—' }}</p>
                  <p class="mt-0.5 at-t-xs at-muted">− {{ (item.costs_a || []).join('; ') || '—' }}</p>
                </div>
                <div class="at-inset p-3">
                  <p class="at-t-sm font-medium at-fg">{{ t('result.option_b') }} · {{ item.option_b || 'B' }}</p>
                  <p class="mt-1 at-t-xs at-fg">+ {{ (item.gains_b || []).join('; ') || '—' }}</p>
                  <p class="mt-0.5 at-t-xs at-muted">− {{ (item.costs_b || []).join('; ') || '—' }}</p>
                </div>
              </div>
              <p v-if="(item.implications || []).length" class="mt-2 at-t-xs at-muted">{{ t('result.conditions') }}: {{ item.implications.join('; ') }}</p>
              <div class="mt-2 flex flex-wrap items-center gap-1.5">
                <template v-if="item.evidence_ids.length">
                  <RefChip v-for="id in item.evidence_ids" :key="id" :id="evidence(id)?.evidence_id || id" :resolved="!!evidence(id)" :clickable="!!evidence(id)" :target="evidenceTarget(id)" @select="locate" />
                </template>
                <span v-else class="at-t-xs at-warn-text">{{ t('result.no_evidence_support') }} · {{ t('result.unverified') }}</span>
              </div>
            </li>
          </ul>
        </section>

        <!-- Recommendations -->
        <section v-if="recommendations.length" id="block-recommendations" class="scroll-mt-20">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.recommendations') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ recommendations.length }}</span>
          </h2>
          <ul class="at-list">
            <li v-for="item in recommendations" :key="item.recommendation_id" :id="'recommendation-' + item.recommendation_id" class="at-row p-4" :class="{ 'at-locate-flash': isHighlighted('recommendation-' + item.recommendation_id) }">
              <p class="at-t-base leading-relaxed at-fg">{{ item.statement }}</p>
              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <span class="at-chip" :class="recStatusClass(item.status)">{{ t(recStatusKey(item.status)) }}</span>
                <span v-if="hasNature(item.claim_type)" class="at-chip" :class="natureClass(item.claim_type)">
                  {{ t('result.data_nature') }}: {{ t(natureKey(item.claim_type)) }}
                </span>
              </div>
              <p v-if="item.limitations.length" class="mt-1.5 at-t-xs at-muted">{{ t('result.applicability') }}: {{ item.limitations.join('; ') }}</p>
              <details class="mt-3">
                <summary class="cursor-pointer select-none at-t-xs font-medium at-dim hover:at-fg">{{ t('result.trace_title') }}</summary>
                <div class="mt-2 border-l at-border pl-3">
                  <p class="at-trace__hint mb-2">{{ t('result.locate_hint') }}</p>
                  <ul v-if="recTrace(item).length" class="at-trace">
                    <li v-for="node in recTrace(item)" :key="node.key" class="at-trace__branch">
                      <div class="at-trace__row">
                        <RefChip :id="node.id" :label="node.resolved ? `${t(chainKey(node.kind))}: ${node.label}` : node.label" :resolved="node.resolved" :clickable="node.resolved" :target="node.target" @select="locate" />
                      </div>
                      <ul v-if="node.children.length" class="at-trace__children">
                        <li v-for="ev in node.children" :key="ev.key" class="at-trace__branch">
                          <div class="at-trace__row">
                            <RefChip :id="ev.id" :label="ev.resolved ? `${t(chainKey(ev.kind))}: ${ev.label}` : ev.label" :resolved="ev.resolved" :clickable="ev.resolved" :target="ev.target" @select="locate" />
                          </div>
                          <ul v-if="ev.children.length" class="at-trace__children">
                            <li v-for="src in ev.children" :key="src.key" class="at-trace__branch">
                              <RefChip :id="src.id" :label="src.resolved ? `${t(chainKey(src.kind))}: ${src.label}` : src.label" :resolved="src.resolved" :clickable="src.resolved" :target="src.target" @select="locate" />
                            </li>
                          </ul>
                        </li>
                      </ul>
                    </li>
                  </ul>
                  <p v-else class="at-t-xs at-warn-text">{{ t('result.no_evidence_support') }}</p>
                </div>
              </details>
            </li>
          </ul>
        </section>

        <!-- Original agent sections -->
        <section v-if="agentSections.length">
          <p class="at-eyebrow mb-4">{{ t('result.original_sections') }}</p>
          <div class="space-y-8">
            <article v-for="(section, idx) in agentSections" :id="`sec-${idx}`" :key="`${section.agent_id}:${section.output_type}`" class="scroll-mt-20">
              <div class="mb-2 flex items-baseline gap-3">
                <span class="font-mono at-t-xs at-dim">{{ String(idx + 1).padStart(2, '0') }}</span>
                <h2 class="at-t-lg font-semibold at-fg">{{ sectionTitle(section) }}</h2>
              </div>
              <p class="mb-3 pl-6 at-t-xs"><span class="at-muted">{{ section.agent_name }}</span> <span class="font-mono at-dim">{{ section.output_type }}</span></p>
              <div class="md-doc pl-6" v-html="renderMarkdown(section.content)"></div>
              <details v-if="Object.keys(section.structured_data).length" class="mt-4 at-card">
                <summary class="cursor-pointer select-none px-4 py-2.5 at-t-xs font-medium at-dim hover:at-fg">
                  {{ t('art.key_data') }} · {{ Object.keys(section.structured_data).length }} fields
                </summary>
                <pre class="max-h-56 overflow-auto border-t at-border px-4 py-3 font-mono at-t-xs leading-relaxed at-muted">{{ prettyJson(section.structured_data) }}</pre>
              </details>
            </article>
          </div>
        </section>

        <!-- Evidence -->
        <section id="block-evidence" class="scroll-mt-20 border-t at-border pt-6">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.evidence') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ evidenceCount }}</span>
          </h2>
          <ul v-if="result.evidence.length" class="at-list">
            <li v-for="(item, i) in result.evidence" :key="item.evidence_id || (item.source_id + '|' + item.claim)" :id="'evidence-' + (item.evidence_id || 'idx-' + i)" class="at-row p-3.5" :class="{ 'at-locate-flash': isHighlighted('evidence-' + (item.evidence_id || 'idx-' + i)) }">
              <p class="at-t-sm leading-relaxed at-fg">{{ item.claim }}</p>
              <p v-if="item.evidence" class="mt-1 at-t-xs leading-relaxed at-dim">{{ item.evidence }}</p>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <span v-if="hasNature(item.claim_type)" class="at-chip" :class="natureClass(item.claim_type)">{{ t(natureKey(item.claim_type)) }}</span>
                <span v-if="item.producer_agent" class="at-t-xs at-dim">{{ item.producer_agent }}</span>
                <span v-if="item.source_id" class="font-mono at-t-xs at-dim">→ {{ item.source_id }}</span>
                <RefChip v-if="item.evidence_id" :id="item.evidence_id" clickable :target="'evidence-' + item.evidence_id" @select="locate" />
              </div>
              <div v-if="usedBy(item.evidence_id || '').length" class="mt-1.5 space-y-0.5">
                <p v-for="line in usedBy(item.evidence_id || '')" :key="line" class="at-t-xs at-dim">{{ t('result.used_by') }}: {{ line }}</p>
              </div>
            </li>
          </ul>
          <p v-else class="at-t-sm at-dim">{{ t('result.no_evidence') }}</p>
        </section>

        <!-- Sources -->
        <section id="block-sources" class="scroll-mt-20 border-t at-border pt-6">
          <h2 class="at-h2 mb-3 flex items-baseline gap-2">
            {{ t('result.sources') }}
            <span class="font-mono at-t-xs font-normal at-dim at-num">{{ sourcesCount }}</span>
          </h2>
          <ol v-if="result.sources.length" class="space-y-3">
            <li v-for="(source, i) in result.sources" :key="source.id" :id="'source-' + source.id" class="flex gap-3" :class="{ 'at-locate-flash': isHighlighted('source-' + source.id) }">
              <span class="font-mono at-t-xs at-dim at-num">{{ String(i + 1).padStart(2, '0') }}</span>
              <div class="min-w-0 flex-1 at-t-sm">
                <p class="at-fg">{{ sourceLabel(source) }}</p>
                <p class="mt-0.5 at-t-xs">
                  <a
                    v-if="href(source.url)"
                    :href="href(source.url) || undefined"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="break-all at-info underline underline-offset-2"
                    :title="source.url"
                  >
                    {{ shortUrl(source.url) }}
                  </a>
                  <span v-else class="at-dim">{{ t('result.offline_no_url') }}</span>
                </p>
                <div class="mt-1 flex flex-wrap items-center gap-2">
                  <span class="at-chip">{{ source.source_type }}</span>
                  <RefChip :id="source.id" clickable :target="'source-' + source.id" @select="locate" />
                  <span v-if="source.retrieved_at" class="font-mono at-t-xs at-dim">{{ source.retrieved_at }}</span>
                </div>
              </div>
            </li>
          </ol>
          <p v-else class="at-t-sm at-dim">{{ t('result.no_sources') }}</p>
        </section>

        <!-- Empty synthesis state -->
        <div
          v-if="!findings.length && !insights.length && !contradictions.length && !uncertainties.length && !tradeoffs.length && !recommendations.length"
          class="at-card flex flex-col items-center gap-2 border-t py-10 text-center"
        >
          <UnitIcon name="inbox" :size="20" class="at-dim" />
          <p class="at-t-sm at-dim">{{ t('result.empty_findings') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
