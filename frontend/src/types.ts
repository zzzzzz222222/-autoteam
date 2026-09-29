// Shared types mirroring the FastAPI DTOs (app/api/models.py).

export interface HealthResponse {
  status: string
  version: string
}

export interface TaskCreated {
  task_id: string
  status: string
}

export interface AgentResultDto {
  status: string
  attempt: number
  error: string | null
  duration: number | null
}

export interface FinalArtifactDto {
  status: string
  title: string
  markdown: string
  sources: SourceDto[]
  evidence: EvidenceDto[]
  sections: SectionDto[]
}

export interface SourceDto {
  id: string
  title: string
  url: string
  source_type: string
  retrieved_at: string
}

export interface EvidenceDto {
  claim: string
  evidence: string
  source_id: string
}

export interface SectionDto {
  title: string
  agent_id: string
  agent_name: string
  output_type: string
  content: string
  structured_data: Record<string, string>
}

export interface TaskSnapshot {
  task_id: string
  task: string
  mode: string
  run_id: string
  status: string
  agent_names: Record<string, string>
  agent_results: Record<string, AgentResultDto>
  layers: string[][]
  edges: { source: string; target: string }[]
  event_count: number
  started_at: number | null
  finished_at: number | null
  created_at: number
  final_artifact: FinalArtifactDto | null
}

export interface TeamAgent {
  id: string
  name: string
  role: string
  capabilities: string[]
  tools: string[]
  layer: number
  status: string
  attempt: number
}

export interface TeamResponse {
  task: string
  agents: TeamAgent[]
  edges: { source: string; target: string }[]
  layers: string[][]
  explanation: {
    task: string
    domain: string
    reasoning: string
    required_capabilities: string[]
    agents: unknown[]
  } | null
}

export interface ArtifactDto {
  artifact_id: string
  agent_id: string
  agent_name: string
  output_type: string
  title: string
  content: string
  structured_data: Record<string, string>
  sources: string[]
  source_records: SourceDto[]
  evidence: EvidenceDto[]
  dependencies: string[]
  created_at: string
  metadata: Record<string, unknown> & { tools_used?: string[]; source_type?: string }
}

export interface ArtifactsResponse {
  task_id: string
  artifacts: ArtifactDto[]
}

export interface ExecutionEvent {
  event_id: string
  run_id: string
  timestamp: number
  type: string
  agent_id: string
  message: string
  metadata: Record<string, unknown> & { tool?: string; offline?: boolean; artifact_id?: string }
}

export interface EventsHistory {
  task_id: string
  events: ExecutionEvent[]
  event_count: number
  done: boolean
}

export interface FinalResultResponse {
  task_id: string
  status: string
  title: string
  markdown: string
  sources: SourceDto[]
  evidence: EvidenceDto[]
  sections: SectionDto[]
}

export type AgentStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'success'
  | 'failed'
  | 'retry'
  | 'skipped'