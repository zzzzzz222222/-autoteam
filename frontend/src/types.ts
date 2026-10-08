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
  partial?: boolean
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
  evidence_id?: string
  producer_agent?: string
  artifact_id?: string
  claim_type?: string
}

// v0.6.0 synthesis payload (all optional)
export interface FindingDto {
  finding_id: string
  statement: string
  evidence_ids: string[]
  supporting_agents: string[]
  support_kind: string
  notes?: string
  claim_type?: string
  derivation?: string
  // v0.6.6: agent agreement vs independent sources, plus the citation check.
  support_level?: string
  evidence_count?: number
  agent_support_count?: number
  independent_source_count?: number
  review_status?: string
  unsupported_parts?: string[]
}

export interface InsightDto {
  insight_id: string
  statement: string
  supporting_evidence_ids: string[]
  supporting_artifact_ids: string[]
  producer_agents: string[]
  contributing_agents?: string[]
  uncertainty: string
  claim_type?: string
  derivation?: string
}

export interface ContradictionDto {
  contradiction_id: string
  claim_a: string
  claim_b: string
  evidence_ids: string[]
  source_ids: string[]
  agents: string[]
  status: string
  resolution: string
}

export interface UncertaintyDto {
  uncertainty_id: string
  statement: string
  evidence_ids: string[]
  kind: string
  note: string
}

export interface TradeoffDto {
  tradeoff_id: string
  dimension: string
  option_a: string
  option_b: string
  gains_a: string[]
  costs_a: string[]
  gains_b: string[]
  costs_b: string[]
  evidence_ids: string[]
  implications: string[]
}

export interface RecommendationDto {
  recommendation_id: string
  statement: string
  supporting_insight_ids: string[]
  supporting_tradeoff_ids: string[]
  supporting_evidence_ids: string[]
  limitations: string[]
  status: string
  claim_type?: string
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
  metadata: Record<string, unknown> & {
    tool?: string
    tool_kind?: string
    offline?: boolean
    artifact_id?: string
  }
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
  findings?: FindingDto[]
  insights?: InsightDto[]
  contradictions?: ContradictionDto[]
  uncertainties?: UncertaintyDto[]
  tradeoffs?: TradeoffDto[]
  recommendations?: RecommendationDto[]
  synthesis_status?: string
  synthesis_degradation_reason?: string
  reference_issues?: string[]
}

export type AgentStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'success'
  | 'failed'
  | 'retry'
  | 'skipped'
  | 'partial'
// M1: a ready-to-draw DAG edge (geometry computed by the parent from the DOM).
export interface GraphEdgeShape {
  id: string
  d: string
  active: boolean
  dim: boolean
}
