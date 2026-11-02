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

/** PROPOSED -> (INVESTIGATING) -> ACCEPTED -> RUNNING -> SHADOW -> DONE -> PROMOTED, or REJECTED. */
export type HypothesisStatus =
  | "PROPOSED"
  | "INVESTIGATING"
  | "ACCEPTED"
  | "REJECTED"
  | "RUNNING"
  | "SHADOW"
  | "DONE"
  | "PROMOTED";

export type HypothesisTarget =
  | "models"
  | "backtesting"
  | "analytics"
  | "features"
  | "rankings"
  | "pick_engine"
  | "decision_rules"
  | "data"
  | "ai"
  | "other";

export type HypothesisDecision = "reject" | "investigate" | "approve_experiment";

export interface StageMove {
  from: string;
  to: string;
  at: string;
  by?: number | null;
  note?: string | null;
}

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
  /** What it would change if ever promoted. */
  target?: HypothesisTarget;
  stage_history?: StageMove[];
  /** The experiment's judged result; gate_passed decides whether it can be promoted. */
  outcome?: Record<string, unknown> | null;
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
  last_v2: {
    name: string;
    code_version: string | null;
    /** Fingerprint of the model code the run used; null for runs stored before 5 Oct 2026. */
    model_code?: string | null;
    dataset_version?: string | null;
    finished_at: string | null;
  } | null;
  v2_due: string | null;
  /** Why research is frozen (no run stores a model), or null. */
  research_frozen?: string | null;
  v2_due_code?: string | null;
  v2_due_vars?: Record<string, string>;
}

/** What covers one fingerprint of the model code (backend `fbi.research.trace`). */
export type CodeStatus =
  "BASELINE" | "PROMOTED" | "AFTER_USE" | "PENDING_SYNC" | "UNTRACED" | "PRE_LEDGER";

/** The CHAMPION row of `intel.promotions` that covers a fingerprint. */
export interface CodePromotionRow {
  id: number;
  decided_by: string;
  decided_at: string;
  reason: string;
  /** What the decision rested on: the hypothesis, the experiments, the gate, the release. */
  evidence: Record<string, unknown>;
}

/** A fingerprint of the model packages that production forecast with in the window. */
export interface CodeFingerprint {
  /** `mc` and ten hex digits; `legacy` for the versions keyed by a repository commit. */
  fingerprint: string;
  status: CodeStatus;
  appeared_at: string;
  last_use: string;
  /** Used in the last two days. Not "the code in force": see `CodePromotions.running_code`. */
  in_force_now: boolean;
  versions: number;
  models: string[];
  /** What it produced in the window, by source: predictions, forecasts, decisions. */
  rows: Record<string, number>;
  promotion: CodePromotionRow | null;
}

export interface CodeCounts {
  fingerprints: number;
  /** The changes since the ledger began: the fingerprints that are not PRE_LEDGER. */
  counted: number;
  /** Of those, the ones with a promotion on record (BASELINE, PROMOTED, AFTER_USE). */
  traced: number;
  untraced: number;
  pending_sync: number;
  after_use: number;
  pre_ledger: number;
}

/** One decision of the ledger the running code carries. */
export interface CodeLedgerEntry {
  fingerprint: string;
  decided_at: string;
  decided_by: string;
  phase: string;
  reason: string;
  baseline: boolean;
  evidence: Record<string, unknown>;
  /** `intel.promotions` has its CHAMPION row. */
  recorded: boolean;
  /** Production forecast with it in the window. */
  used: boolean;
}

/** The model code against its promotions (plan F12). */
export interface CodePromotions {
  now: string;
  since: string;
  days: number;
  /** The fingerprint of the model code this server runs. */
  running_code: string;
  /** The last entry of the ledger: the code the ledger says production forecasts with. */
  ledger_in_force: string | null;
  ledger_since: string | null;
  in_force_matches_running: boolean;
  fingerprints: CodeFingerprint[];
  counts: CodeCounts;
  /** `traced / counted` as a fraction of 1; null when nothing changed since the ledger began. */
  coverage: number | null;
  ledger: CodeLedgerEntry[];
  /** The promotions of the other kinds of change in the same window, for context. */
  other: Record<string, number>;
}
