<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import type { FinalResultResponse } from '@/types'

const props = defineProps<{ taskId: string }>()
const result = ref<FinalResultResponse | null>(null)
const error = ref<string | null>(null)
const coped = ref(false)

async function load() {
  try {
    result.value = await api.getResult(props.taskId)
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)
watch(() => props.taskId, load)

async function copyMarkdown() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.markdown)
    coped.value = true
    setTimeout(() => (coped.value = false), 1500)
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

function anchorId(idx: number): string {
  return `sec-${idx}`
}

async function scrollToSection(idx: number) {
  const el = document.getElementById(anchorId(idx))
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const toc = computed(() => result.value?.sections.map((s, i) => ({ title: s.title, index: i })) ?? [])

function renderMarkdown(md: string): string {
  return escapeHtml(md)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => `<p>${line}</p>`)
    .join('')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
</script>

<template>
  <div class="grid grid-cols-12 gap-6">
    <!-- TOC -->
    <nav class="col-span-3">
      <div class="sticky top-6 space-y-4">
        <div v-if="result" class="rounded-lg border border-zinc-200 bg-white p-4">
          <div class="mb-3 flex items-center gap-2">
            <StatusBadge :status="result.status" />
          </div>
          <p class="text-sm font-semibold text-zinc-900">{{ result.title }}</p>
          <div class="mt-3 border-t border-zinc-100 pt-3 text-xs text-zinc-500">
            <p>{{ result.sources.length }} Sources</p>
            <p>{{ result.evidence.length }} Evidence</p>
            <p>{{ toc.length }} Sections</p>
          </div>
          <div class="mt-3 flex gap-2 border-t border-zinc-100 pt-3">
            <button
              type="button"
              class="rounded border border-zinc-300 px-2.5 py-1 text-xs text-zinc-600 transition-colors hover:bg-zinc-50"
              @click="copyMarkdown"
            >
              {{ coped ? 'Copied ✓' : 'Copy' }}
            </button>
            <button
              type="button"
              class="rounded border border-zinc-300 px-2.5 py-1 text-xs text-zinc-600 transition-colors hover:bg-zinc-50"
              @click="downloadMarkdown"
            >
              Save .md
            </button>
          </div>
        </div>

        <div v-if="toc.length" class="rounded-lg border border-zinc-200 bg-white p-2">
          <ul class="space-y-0.5 text-xs">
            <li v-for="item in toc" :key="item.index">
              <button
                type="button"
                class="w-full truncate rounded px-2 py-1.5 text-left text-zinc-600 transition-colors hover:bg-zinc-50 hover:text-zinc-900"
                @click="scrollToSection(item.index)"
              >
                {{ item.title }}
              </button>
            </li>
          </ul>
        </div>
      </div>
    </nav>

    <!-- Markdown document -->
    <section class="col-span-9">
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
      <p v-else-if="!result" class="rounded-lg border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-400">
        The final deliverable is not ready yet — the team is still working.
      </p>

      <template v-else>
        <!-- Executive summary of the assembled artifact -->
        <div class="rounded-lg border border-zinc-200 bg-white p-5">
          <h2 class="text-lg font-semibold text-zinc-900">{{ result.title }}</h2>
          <p class="mt-2 text-xs text-zinc-400">
            Assembled from real agent artifacts · status
          <StatusBadge :status="result.status" class="ml-1" />
          </p>
        </div>

        <div v-for="(section, idx) in result.sections" :key="section.agent_id + idx" :id="anchorId(idx)" class="mt-4 scroll-mt-24 rounded-lg border border-zinc-200 bg-white p-5">
          <div class="mb-2 flex items-center justify-between">
            <h3 class="font-semibold text-zinc-800">{{ section.title }}</h3>
            <span class="text-xs text-zinc-400">{{ section.agent_name }} · {{ section.output_type }}</span>
          </div>
          <div v-html="renderMarkdown(section.content)" class="prose-markdown text-sm text-zinc-700"></div>
          <div v-if="Object.keys(section.structured_data).length" class="mt-3 rounded bg-zinc-50 p-3 text-xs">
            <pre class="whitespace-pre-wrap text-zinc-600">{{ JSON.stringify(section.structured_data, null, 2) }}</pre>
          </div>
        </div>

        <!-- Sources -->
        <div class="mt-4 rounded-lg border border-zinc-200 bg-white p-5">
          <h3 class="mb-3 font-semibold text-zinc-800">Sources</h3>
          <ol v-if="result.sources.length" class="space-y-2">
            <li v-for="(source, i) in result.sources" :key="source.id" class="flex gap-3 text-sm">
              <span class="font-mono text-xs text-zinc-400">{{ String(i + 1).padStart(2, '0') }}</span>
              <div class="min-w-0">
                <p class="text-zinc-700">{{ source.title }}</p>
                <p class="text-xs text-zinc-400">
                  <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="underline">
                    {{ source.url }}
                  </a>
                  <span v-else>(offline source — no URL)</span>
                  <span class="ml-2 rounded bg-zinc-100 px-1 py-0.5 text-[10px]">{{ source.source_type }}</span>
                </p>
              </div>
            </li>
          </ol>
          <p v-else class="text-sm text-zinc-400">No sources recorded.</p>
        </div>

        <!-- Evidence -->
        <div class="mt-4 rounded-lg border border-zinc-200 bg-white p-5">
          <h3 class="mb-3 font-semibold text-zinc-800">Evidence</h3>
          <ul v-if="result.evidence.length" class="space-y-3">
            <li v-for="(ev, i) in result.evidence" :key="i" class="text-sm">
              <p class="text-zinc-700">
                <span class="font-mono text-xs text-zinc-400">#{{ i + 1 }}</span> {{ ev.claim }}
              </p>
              <p class="mt-0.5 pl-6 text-xs text-zinc-400">{{ ev.evidence }}</p>
            </li>
          </ul>
          <p v-else class="text-sm text-zinc-400">No evidence recorded.</p>
        </div>
      </template>
    </section>
  </div>
</template>