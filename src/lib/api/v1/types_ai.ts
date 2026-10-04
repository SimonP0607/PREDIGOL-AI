/** The AI layer (GATE H) and the evolution loop (GATE I), as the Admin API returns them. */

export interface AiBudget {
  month: string;
  cap_usd: string;
  spent_usd: string;
  left_usd: string;
}

export type AiRunKind = "ask" | "daily_report" | "pick_review";
export type AiRunStatus = "running" | "ok" | "failed" | "not_configured" | "over_budget";

export interface AiRunRow {
  id: number;
  kind: AiRunKind;
  model: string | null;
  started_at: string;
  finished_at: string | null;
  status: AiRunStatus;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  tool_calls: number;
  error: string | null;
  detail: Record<string, unknown>;
}

export interface AiStatus {
  llm_configured: boolean;
  model: string | null;
  search_configured: boolean;
  missing: string[];
  budget: AiBudget;
  questions_today: number;
  questions_per_day: number;
  last_runs: AiRunRow[];
  schedule: Record<string, string>;
}

export type ClaimGrade = "CONFIRMED" | "REPORTED" | "RUMOR";

export interface AiClaimRow {
  id: number;
  fixture_id: number | null;
  team_id: number | null;
  claim: string;
  source_url: string;
  also_urls: string[];
  publisher: string | null;
  published_at: string | null;
  retrieved_at: string;
  confidence: ClaimGrade;
}

export type SetSource = "qualified" | "evaluation";

export interface AiReport {
  id: number;
  run_id: number;
  day: string;
  source: SetSource;
  markdown: string;
  claims: AiClaimRow[];
  created_at: string;
  run_status: AiRunStatus;
  model: string | null;
  cost_usd: string;
}

export type FlagSeverity = "info" | "warn" | "review";

export interface AiFlagRow {
  id: number;
  run_id: number;
  engine: "rules" | "model";
  set_id: number | null;
  rank: number | null;
  fixture_id: number;
  match: string;
  code: string;
  severity: FlagSeverity;
  note: string;
  claim_ids: number[];
  created_at: string;
}

export interface AiFlags {
  day: string;
  source: SetSource;
  set_id: number | null;
  flags: AiFlagRow[];
}

export type HypothesisStatus = "PROPOSED" | "ACCEPTED" | "REJECTED" | "RUNNING" | "DONE";

export interface Hypothesis {
  id: number;
  proposed_by: "ai" | "owner" | "system";
  title: string;
  hypothesis: string;
  rationale: string;
  evidence: Record<string, unknown>;
  status: HypothesisStatus;
  experiment_ids: number[];
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
}

export interface MemoryEntry {
  id: number;
  topic: string;
  finding: string;
  evidence: Record<string, unknown>;
  source: "research_v2" | "prospective" | "audit" | "owner";
  created_at: string;
  versions: number;
}

export interface EvolutionOverview {
  loop: string[];
  hypotheses: Hypothesis[];
  memory: MemoryEntry[];
  last_monitor: string | null;
  last_v2: { name: string; code_version: string | null; finished_at: string | null } | null;
  v2_due: string | null;
}
