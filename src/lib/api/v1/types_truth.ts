/** Data truth (Admin Console): the audit against the provider, freshness, tables, the model gate. */

export type FreshnessState = "FRESH" | "STALE" | "UNKNOWN" | "UNAVAILABLE";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type FindingKind =
  | "mismatch"
  | "missing_in_db"
  | "missing_in_api"
  | "not_stored"
  | "stale"
  | "provider_lag"
  | "inconsistent";

export interface TruthRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  requests: number;
  seed: number | null;
  findings: number;
  by_severity: Partial<Record<Severity, number>>;
  report_dir: string | null;
}

export interface TruthMatrixRow {
  dataset: string;
  api: string;
  db: string;
  difference: string;
  checked: number;
  matched: number;
  findings: number;
  worst: Severity | null;
  freshness: string;
  freshness_status: FreshnessState | null;
  model_safe: string;
  role: "REQUIRED" | "OPTIONAL" | "NOT_USED" | "UNAVAILABLE_BY_PROVIDER";
  /** The api / db columns as a message key and its numbers (absent on audits before 2026-10-04). */
  api_key?: { key?: string; params?: Record<string, number> };
  db_key?: { key?: string; params?: Record<string, number> };
  by_kind?: Partial<Record<FindingKind, number>>;
  freshness_counts?: Partial<Record<FreshnessState, number>>;
  safe_code?: "yes" | "yes_optional" | "partial" | "no" | "na" | null;
  safe_reasons?: string[];
}

export interface FreshnessDataset {
  dataset: string;
  sla: string;
  entity: string;
  status: FreshnessState;
  label: string;
  total: number;
  counts: Record<FreshnessState, number>;
  by_competition: Array<{ competition: string } & Record<FreshnessState, number>>;
  examples: Partial<Record<FreshnessState, string[]>>;
}

export interface FreshnessReport {
  measured_at: string;
  datasets: FreshnessDataset[];
}

export interface GateModel {
  model: string;
  passing: number;
  blocked: number;
  blocked_by: Record<string, number>;
  needs: Record<string, string>;
}

export interface GateFixture {
  provider_fixture_id: number;
  competition: string;
  kickoff_at: string;
  datasets: Record<string, { state: string; why: string }>;
  models: Record<string, boolean>;
}

export interface GateReport {
  measured_at: string;
  horizon_hours: number;
  fixtures: number;
  models: GateModel[];
  sample: GateFixture[];
}

export interface TruthDatasetSummary {
  dataset: string;
  checked: number;
  matched: number;
  findings: number;
  by_kind: Partial<Record<FindingKind, number>>;
  by_severity: Partial<Record<Severity, number>>;
  worst: Severity | null;
  difference: string;
  requests: number;
  notes: string[];
  by_field: Array<{ field: string; kind: FindingKind; severity: Severity; n: number }>;
}

export interface TruthSummary {
  run: TruthRun;
  matrix: TruthMatrixRow[];
  freshness: FreshnessDataset[];
  gate: {
    horizon_hours?: number;
    fixtures?: number;
    by_model?: Record<
      string,
      { pass: number; blocked: number; blocked_by: Record<string, number> }
    >;
  };
  datasets: Record<string, TruthDatasetSummary>;
  failures: string[];
}

export interface TruthFinding {
  id: number;
  dataset: string;
  entity: string;
  field: string;
  kind: FindingKind;
  severity: Severity;
  api_value: string | null;
  db_value: string | null;
  note: string;
}

export type TableReason =
  | "not_covered"
  | "no_table"
  | "no_match_yet"
  | "reflects_last_match"
  | "provider_not_updated"
  | "not_asked_since";

export interface StandingsAuditRow {
  competition_id: number;
  competition: string;
  country: string | null;
  provider_league_id: number;
  season: number;
  status: FreshnessState;
  reason_code: TableReason;
  reason: string;
  snapshot_at: string | null;
  checked_at: string | null;
  changed_at: string | null;
  provider_updated_at: string | null;
  last_finished_at: string | null;
  rows: number;
  rows_skipped: number;
  groups: number;
  extended: boolean;
}

export interface DataRepair {
  id: number;
  repaired_at: string;
  rule: string;
  entity: string;
  entity_id: number;
  provider_ref: number | null;
  field: string;
  before_value: string | null;
  after_value: string | null;
  reason: string;
}

export interface FindingsQuery {
  dataset?: string | undefined;
  severity?: Severity | undefined;
  kind?: FindingKind | undefined;
  limit?: number;
  offset?: number;
}
