// Thin typed client for the AutoTeam Web API.
import type {
  ArtifactsResponse,
  EventsHistory,
  ExecutionEvent,
  FinalResultResponse,
  HealthResponse,
  TaskCreated,
  TaskSnapshot,
  TeamResponse,
} from '@/types'

const BASE = '/api'

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${res.url}`)
  }
  return (await res.json()) as T
}

export const api = {
  health: () => json<HealthResponse>(`${BASE}/health`),

  createTask: (task: string, mode: 'real' | 'offline') =>
    json<TaskCreated>(`${BASE}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task, mode }),
    }),

  listTasks: () => json<TaskSnapshot[]>(`${BASE}/tasks`),
  getTask: (taskId: string) => json<TaskSnapshot>(`${BASE}/tasks/${taskId}`),
  getTeam: (taskId: string) => json<TeamResponse>(`${BASE}/tasks/${taskId}/team`),
  getArtifacts: (taskId: string) =>
    json<ArtifactsResponse>(`${BASE}/tasks/${taskId}/artifacts`),
  getResult: (taskId: string) =>
    json<FinalResultResponse>(`${BASE}/tasks/${taskId}/result`),
  getEventsHistory: (taskId: string) =>
    json<EventsHistory>(`${BASE}/tasks/${taskId}/events`),
}

/** Open an SSE stream for a task; invokes ``onEvent`` for each parsed event. */
export function subscribeEvents(taskId: string, onEvent: (event: ExecutionEvent) => void): () => void {
  const source = new EventSource(`${BASE}/tasks/${taskId}/stream`)
  source.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as ExecutionEvent)
    } catch {
      /* ignore malformed frame */
    }
  }
  source.onerror = () => {
    // Server closes the stream when done; EventSource will auto-reconnect,
    // which stops once the server side generator returns.
    source.close()
  }
  return () => source.close()
}