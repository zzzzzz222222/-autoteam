"""Synthesis prompt texts (v0.6.2, extracted for readability).

Kept as plain constants so the staged and single-shot prompts share exactly the
same grounding rules.
"""

FULL_SCHEMA_TEXT = """

Return JSON matching SynthesisResult with:
- summary: 3-5 sentence executive summary of the COMBINED result
- key_findings: what multiple agents together establish (findings[] with
  finding_id, statement, evidence_ids, supporting_agents, support_kind,
  claim_type, derivation)
- supported_findings: findings backed by 2+ evidence items / agents
- single_source_findings: findings backed by exactly one source
- cross_agent_insights: judgments that COMBINE at least two DIFFERENT agents'
  evidence into a new conclusion (insights[] with insight_id, statement,
  supporting_evidence_ids, supporting_artifact_ids, producer_agents,
  uncertainty, claim_type, derivation)
- contradictions: claims that conflict (contradictions[] with
  contradiction_id, claim_a, claim_b, evidence_ids, source_ids, agents,
  status='resolved'|'unresolved', resolution)
- uncertainties: thin spots (uncertainties[] with uncertainty_id, statement,
  evidence_ids, kind='insufficient_evidence'|'single_source'|'conflicting'|'vague')
- tradeoffs: real tensions from THIS task (tradeoffs[] with tradeoff_id,
  dimension, option_a, option_b, gains_a, costs_a, gains_b, costs_b,
  evidence_ids, implications)
- recommendations: proposals traceable to insights/tradeoffs/evidence
  (recommendations[] with recommendation_id, statement,
  supporting_insight_ids, supporting_tradeoff_ids, supporting_evidence_ids,
  limitations, status='supported'|'potential'|'unsupported')"""

SHARED_RULES_TEXT = """Rules:
1. Only cite evidence_ids listed above. Never invent ids or URLs.
2. If evidence is thin, say so in uncertainties — do not fabricate certainty.
3. Recommendations with no supporting evidence must use status='unsupported'.
4. No quality scores, no self-grading, no percentages of confidence.
5. Write statements in the same language as the TASK.
6. claim_type classifies the DATA NATURE of a claim. Use exactly one of:
   source_fact (a source states it directly), derived_estimate (computed from
   traceable inputs — put the inputs and method in derivation),
   planning_assumption (a product/business goal or forecast),
   unverified_claim (thin or unverifiable support). If you are unsure, leave
   claim_type empty — never guess. Never call a planning target a market fact.
7. A cross_agent_insight must combine at least two different agents' evidence.
   If only one agent supports it, keep it out of cross_agent_insights (or flag
   it in uncertainty) — do not dress a single-agent point as cross-agent."""
