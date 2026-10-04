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

// ── odds coverage (BOOKMAKER_COVERAGE_REPORT) ─────────────────────────────────

export type CoverageState =
  "NOT_ASKED" | "NOT_COVERED" | "UNPRICED_BY_PROVIDER" | "THIN" | "PARTIAL" | "COVERED";
export type BookmakerCoverageState = "ACTIVE" | "DORMANT" | "CATALOGUE_ONLY";
export type LocalCoverageState = "PRICED_BY_PROVIDER_BRAND" | "CATALOGUE_ONLY" | "NOT_IN_PROVIDER";
export type SourceAccess =
  "ACTIVE" | "FREE_NEEDS_OWNER" | "PAYMENT_REQUIRED" | "CLOSED" | "REJECTED";
export type MissCause = "worker_down" | "known_too_late" | "kickoff_moved" | "missed_while_up";

export interface CoverageCompetition {
  competition_id: number;
  competition: string;
  country: string | null;
  season: number;
  provider_league_id: number | null;
  flag_odds: boolean | null;
  fixtures: number;
  asked: number;
  priced: number;
  captured: number;
  recovered: number;
  priced_two_plus: number;
  median_bookmakers: number | null;
  provider_share: number;
  capture_share: number;
  bookmakers: Record<string, number>;
  markets: Record<string, number>;
  misses: Partial<Record<MissCause, number>>;
  upcoming: Partial<Record<FreshnessState, number>>;
  state: CoverageState;
  reason: string;
}

export interface CoverageBookmaker {
  provider_bookmaker_id: number;
  name: string;
  state: BookmakerCoverageState;
  fixtures: number;
  share: number;
  competitions: number;
  countries: number;
  markets: Record<string, number>;
  first_seen: string | null;
  last_seen: string | null;
  name_missing: boolean;
}

export interface CoverageMarket {
  market_key: string;
  fixtures: number;
  share: number;
  bookmakers: number;
  median_bookmakers: number | null;
}

export interface CoverageCountry {
  country: string;
  competitions: number;
  fixtures: number;
  priced: number;
  captured: number;
  bookmakers: number;
}

export interface CoverageLocal {
  brand: string;
  domain: string;
  company: string;
  state: LocalCoverageState;
  provider_names: string[];
  priced_fixtures: number;
  colombian_edition_confirmed: boolean;
  note: string;
}

export interface OddsSourceProfile {
  key: string;
  name: string;
  kind: string;
  access: SourceAccess;
  bookmakers: string;
  colombian_books: string[];
  closing_line: string;
  cost: string;
  decision: string;
  sources: string[];
}

export interface OddsCoverageReport {
  measured_at: string;
  since: string;
  until: string;
  days: number;
  first_capture: string | null;
  fixtures: number;
  asked: number;
  priced: number;
  captured: number;
  recovered: number;
  misses: Partial<Record<MissCause, number>>;
  worker_down_hours: number;
  critical: string[];
  competitions: CoverageCompetition[];
  bookmakers: CoverageBookmaker[];
  markets: CoverageMarket[];
  countries: CoverageCountry[];
  local: CoverageLocal[];
  local_source: Record<string, string>;
  sources: OddsSourceProfile[];
}
