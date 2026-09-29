import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, subscribeEvents } from '@/api/client'
import type { AgentStatus, ExecutionEvent, TaskSnapshot } from '@/types'

export const useTeamStore = defineStore('team', () => {
  const tasks = ref<TaskSnapshot[]>([])
  const current = ref<TaskSnapshot | null>(null)
  const events = ref<ExecutionEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let unsubscribe: (() => void) | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function fetchList() {
    try {
      tasks.value = await api.listTasks()
    } catch (err) {
      error.value = String(err)
    }
  }

  let loadSeq = 0

  async function loadTask(taskId: string) {
    const seq = ++loadSeq
    loading.value = true
    error.value = null
    try {
      const snap = await api.getTask(taskId)
      const hist = await api.getEventsHistory(taskId)
      // ignore stale responses when the user switched tasks mid-flight
      if (seq !== loadSeq) return
      current.value = snap
      events.value = hist.events
    } catch (err) {
      if (seq === loadSeq) error.value = String(err)
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  function startStream(taskId: string) {
    stopStream()
    unsubscribe = subscribeEvents(taskId, (event) => {
      // SSE replays from index 0 — skip frames already loaded via getEventsHistory
      if (!events.value.some((e) => e.event_id === event.event_id)) {
        events.value.push(event)
      }
      void refresh()
    })
    pollTimer = setInterval(() => void refresh(), 2500)
  }

  async function refresh() {
    if (!current.value) return
    try {
      const snap = await api.getTask(current.value.task_id)
      const wasRunning = current.value.status === 'running'
      current.value = snap
      const idx = tasks.value.findIndex((t) => t.task_id === snap.task_id)
      if (idx >= 0) tasks.value[idx] = snap
      // stop polling once the run finishes (final state pulled from SSE close)
      if (wasRunning && snap.status !== 'running') stopStream()
    } catch {
      /* transient polling failure — ignore */
    }
  }

  function stopStream() {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const agentStatuses = computed<Record<string, AgentStatus>>(() => {
    const map: Record<string, AgentStatus> = {}
    const snapshot = current.value
    if (!snapshot) return map
    for (const agentId of Object.keys(snapshot.agent_names)) {
      const result = snapshot.agent_results[agentId]
      if (!result) {
        map[agentId] = 'pending'
        continue
      }
      if (result.status === 'success') {
        map[agentId] = 'success'
      } else if (result.status === 'running') {
        map[agentId] = 'running'
      } else if (result.status === 'failed') {
        map[agentId] = 'failed'
      } else if (result.status === 'skipped') {
        map[agentId] = 'skipped'
      } else {
        map[agentId] = result.status as AgentStatus
      }
    }
    return map
  })

  const status = computed(() => current.value?.status ?? 'idle')
  const isRunning = computed(() => status.value === 'running' || current.value === null && loading.value)
  const evidenceCount = computed(() => current.value?.final_artifact?.evidence.length ?? 0)
  const sourceCount = computed(() => current.value?.final_artifact?.sources.length ?? 0)

  return {
    tasks,
    current,
    events,
    loading,
    error,
    fetchList,
    loadTask,
    startStream,
    stopStream,
    agentStatuses,
    status,
    isRunning,
    evidenceCount,
    sourceCount,
  }
})