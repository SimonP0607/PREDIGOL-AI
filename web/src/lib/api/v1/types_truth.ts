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
  | "inconsistent"
  | "provider_contradiction";

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

export type DatasetClass = "FRESH" | "STALE" | "INCOMPLETE" | "INVALID" | "UNKNOWN";
export type ModelEligibility = "MODEL_READY" | "NOT_MODEL_READY" | "NOT_USED";

/** One of the fourteen datasets with the evidence for its class (GET /admin/data/datasets). */
export interface DatasetRegisterRow {
  dataset: string;
  klass: DatasetClass;
  model: ModelEligibility;
  model_reason: string;
  role: string;
  endpoints: string[];
  sla: string;
  freshness: string;
  /** Fresh share of what we are responsible for (the provider's own gaps excluded). */
  coverage: number | null;
  /** Share the provider does not have (its coverage flag or its lag). */
  provider_gap: number | null;
  last_capture: string | null;
  last_write: string | null;
  rows: number;
  errors_24h: number;
  failed_runs_24h: number;
  open_findings: number;
  blockers: string[];
  notes: string[];
  /** The six answers per dataset; entity counts except REQUEST_FAILED (runs, 24 h) and NORMALIZATION_FAILED (issues). */
  states?: Partial<Record<DatasetState, number>>;
}

export const DATASET_STATES = [
  "VALID",
  "STALE",
  "NOT_REQUESTED",
  "PROVIDER_HAS_NO_DATA",
  "REQUEST_FAILED",
  "NORMALIZATION_FAILED",
] as const;
export type DatasetState = (typeof DATASET_STATES)[number];

export interface DatasetRegister {
  measured_at: string;
  dataset_version: string | null;
  dataset_version_status: string | null;
  rows: DatasetRegisterRow[];
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

// ── historical validation (GATE C) ────────────────────────────────────────────

export type DataClass = "MODEL_READY" | "PARTIAL" | "PRODUCT_ONLY" | "INSUFFICIENT";
export type ValidationState = "INGESTED" | "VALIDATED" | "HISTORICAL_APPROVED" | "QUARANTINED";

export interface ValidationSummary {
  rule_version: string | null;
  computed_at: string | null;
  fixtures: number;
  states: Partial<Record<ValidationState, number>>;
  failed: Record<string, number>;
  classes: Partial<Record<DataClass, number>>;
  approved_by_segment: Record<string, number>;
}

export interface CompetitionScoreRow {
  competition_season_id: number;
  competition_id: number;
  competition: string;
  country: string | null;
  season: number;
  is_current: boolean;
  is_tracked: boolean;
  segment: string;
  data_class: DataClass;
  score: number;
  finished: number;
  approved: number;
  quarantined: number;
  components: Record<string, number>;
  reasons: string[];
  computed_at: string;
}

export interface QuarantinedFixture {
  fixture_id: number;
  provider_fixture_id: number;
  competition: string;
  season: number;
  kickoff_at: string;
  home: string;
  away: string;
  status_short: string;
  failed: string[];
}

export interface ScoresQuery {
  class?: DataClass;
  country?: string;
  q?: string;
  current?: boolean;
  tracked?: boolean;
  limit?: number;
  offset?: number;
}

/** Data truth audit V2 (GATE: DATA TRUTH AUDIT V2) - one run per audit command. */
export interface TruthV2Run {
  id: number;
  kind: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  requests: number;
  summary: Record<string, unknown>;
  report_dir: string | null;
}

export type EvidenceStatus = "OPEN" | "FIXED" | "ACCEPTED" | "MONITOR" | "CLEARED";
export type EvidenceFault = "provider" | "predigol" | "none" | "undetermined";

/** One E-XXX entry of the evidence ledger. */
export interface EvidenceEntry {
  code: string;
  key: string;
  area: string;
  issue_type: string;
  severity: Severity;
  at_fault: EvidenceFault;
  entity: string | null;
  claim: string;
  api_evidence: Record<string, unknown> | null;
  db_evidence: Record<string, unknown> | null;
  external_evidence: Record<string, unknown> | null;
  root_cause: string | null;
  fix: string | null;
  test: string | null;
  status: EvidenceStatus;
  first_seen_at: string;
  last_seen_at: string;
  times_seen: number;
}

export interface TruthV2Overview {
  runs: TruthV2Run[];
  ledger: EvidenceEntry[];
  /** status -> severity -> entries */
  counts: Record<string, Record<string, number>>;
}
