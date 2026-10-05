/**
 * Contracts of the FastAPI product API (/api/v1), mirrored by hand from the
 * Pydantic models in football-intelligence-v2 (src/fbi/api/contracts).
 *
 * Decimal fields arrive as strings ("2.050") so that no precision is lost in
 * transit; parse them only where they are displayed.
 */

export type Dec = string;
export type Iso = string;

export type DataStatus = "ok" | "empty" | "insufficient_data" | "not_available";

export interface Meta {
  generated_at: Iso;
  api_version: "v1";
  count: number | null;
  total: number | null;
  limit: number | null;
  offset: number | null;
  data_as_of: Iso | null;
}

export interface Envelope<T> {
  status: DataStatus;
  data: T;
  reason: string | null;
  meta: Meta;
}

export interface Section<T> {
  status: DataStatus;
  data: T;
  reason: string | null;
}

export type StatusGroup = "scheduled" | "live" | "finished" | "cancelled" | "postponed";

export interface TeamRef {
  id: number;
  name: string;
  provider_team_id: number;
  /** The provider's crest URL, as stored. Null: not told. */
  logo_url?: string | null;
}

export interface CompetitionRef {
  id: number;
  name: string;
  country: string | null;
  provider_league_id: number;
  season: number;
  competition_type: string;
  is_tracked: boolean;
  logo_url?: string | null;
  flag_url?: string | null;
  country_code?: string | null;
}

export interface VenueRef {
  id: number;
  name: string;
  city: string | null;
}

export interface Score {
  home: number;
  away: number;
  ht_home: number | null;
  ht_away: number | null;
  et_home: number | null;
  et_away: number | null;
  pen_home: number | null;
  pen_away: number | null;
  outcome_1x2: "Home" | "Draw" | "Away";
  total_goals: number;
  btts: boolean;
  source_payload_hash: string | null;
  source_fetched_at: Iso | null;
}

export interface Lineage {
  provider: string;
  provider_fixture_id: number;
  first_seen_at: Iso;
  updated_at: Iso;
  recorded: boolean;
  source_payload_hash: string | null;
  source_fetched_at: Iso | null;
  source_endpoint: string | null;
  source_params: Record<string, string> | null;
  source_run_id: number | null;
  source_job_type: string | null;
  note: string | null;
}

export interface RunSummary {
  id: number;
  job_type: string;
  job_name: string;
  status: "running" | "completed" | "partial" | "failed" | "aborted" | "interrupted" | "stale";
  started_at: Iso;
  finished_at: Iso | null;
  duration_ms: number | null;
  api_calls: number;
  payloads_stored: number;
  rows_written: number;
  rows_updated: number;
  errors: number;
  last_error: string | null;
  notes: string | null;
  /** host:pid of the process that opened the run (since 5 Oct 2026). */
  owner?: string | null;
  /** Last sign of life of the run. */
  heartbeat_at?: Iso | null;
  /** Past it, the run watchdog closes a still-open run as stale. */
  deadline_at?: Iso | null;
}

export interface OddsSummary {
  snapshots: number;
  bookmakers: number;
  markets: number;
  first_captured_at: Iso | null;
  last_captured_at: Iso | null;
  near_close_snapshots: number;
}

export interface MatchSummary {
  id: number;
  provider_fixture_id: number;
  kickoff_at: Iso;
  status_short: string;
  status_group: StatusGroup;
  round: string | null;
  competition: CompetitionRef;
  home: TeamRef;
  away: TeamRef;
  score: Score | null;
  odds: OddsSummary;
  predictions: number;
  awaiting_result: boolean;
}

export interface MarketQuote {
  bookmaker_id: number;
  bookmaker: string;
  market_key: string;
  selection: string;
  line: Dec;
  odds_decimal: Dec;
  /** 1/odds. Raw: the bookmaker margin is still in it. */
  implied_probability: Dec;
  captured_at: Iso;
  minutes_to_ko: number;
  source: "prematch" | "live";
  payload_hash: string;
}

export interface PredictionRow {
  model: string;
  model_version: string;
  /** 'backtest': a historical replay made walk-forward; 'forecast': made in real time before kick-off. */
  kind: "backtest" | "forecast";
  backtest_session_id: number | null;
  market_key: string;
  selection: string;
  line: Dec;
  p_raw: Dec;
  p_calibrated: Dec;
  /** Null when no interval was computed — never a zero-width interval. */
  p_lo: Dec | null;
  p_hi: Dec | null;
  data_cutoff_ts: Iso;
  feature_set_hash: string;
  created_at: Iso;
}

export type TimelineState = "done" | "pending" | "skipped" | "failed";

export interface TimelineEvent {
  key: string;
  label: string;
  detail: string;
  at: Iso | null;
  state: TimelineState;
}

export interface MatchDetail {
  match: MatchSummary;
  venue: VenueRef | null;
  lineage: Lineage;
  markets: Section<MarketQuote[]>;
  predictions: Section<PredictionRow[]>;
  timeline: TimelineEvent[];
}

/** What the product shows for a fixture (GET /matches/{id}); MatchDetail is the Admin Console's. */
export type PriceStatus =
  "PRICED" | "THIN_PRICE" | "PRICE_PENDING" | "PRICE_UNAVAILABLE" | "NOT_COVERED";

/** The model's own number for a market no bookmaker of ours prices (never a price, never a pick). */
export interface ModelNoPriceView {
  status: "MODEL_INTERESTING_NO_PRICE" | "PRICE_UNAVAILABLE";
  selection: string;
  probability: Dec;
  fair_odds: Dec;
  min_odds: Dec;
  model: string;
  rule_version: string;
  evaluation_mode: boolean;
  data_cutoff_ts: Iso;
}

export interface MarketPriceStatus {
  market_key: string;
  line: Dec;
  status: PriceStatus;
  bookmakers: number;
  last_capture: Iso | null;
  model_view: ModelNoPriceView | null;
}

export interface MatchView {
  match: MatchSummary;
  venue: VenueRef | null;
  markets: Section<MarketQuote[]>;
  /** Before kick-off: each core market's price status (absent from older APIs). */
  price_status?: MarketPriceStatus[];
}

export interface SeasonSummary {
  id: number;
  season: number;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  has_odds: boolean;
  fixtures: number;
  finished: number;
  with_results: number;
}

export interface CompetitionSummary {
  id: number;
  provider_league_id: number;
  name: string;
  country: string | null;
  type: string;
  competition_type: string;
  tier: number | null;
  is_tracked: boolean;
  seasons: number;
  current_season: number | null;
  fixtures: number;
  teams: number;
  logo_url?: string | null;
  flag_url?: string | null;
  country_code?: string | null;
}

export interface CompetitionDetail {
  competition: CompetitionSummary;
  seasons: SeasonSummary[];
  teams: TeamRef[];
}

export interface TeamSummary {
  id: number;
  provider_team_id: number;
  name: string;
  country: string | null;
  fixtures: number;
  results: number;
  logo_url?: string | null;
}

export interface TeamRecord {
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  /** "competition_season" (one competition, one season) or "all" (everything stored, from `since`). */
  scope?: string;
  competition?: string | null;
  competition_type?: string | null;
  season?: number | null;
  since?: Iso | null;
  competitions?: number | null;
}

export interface TeamDetail {
  team: TeamSummary;
  venue: VenueRef | null;
  /** The domestic league's current season (a national side: its latest competition). */
  record: Section<TeamRecord | null>;
  /** Every competition of the current campaign. */
  records?: Section<TeamRecord[]> | null;
  /** Everything stored, labelled as such. */
  lifetime?: Section<TeamRecord | null> | null;
  recent: MatchSummary[];
  upcoming: MatchSummary[];
}

export interface OddsPoint {
  captured_at: Iso;
  odds_decimal: Dec;
  minutes_to_ko: number;
  source: "prematch" | "live";
  payload_hash: string;
}

export interface OddsSeries {
  bookmaker_id: number;
  bookmaker: string;
  market_key: string;
  selection: string;
  line: Dec;
  points: OddsPoint[];
}

export interface NearCloseQuote {
  bookmaker: string;
  market_key: string;
  selection: string;
  line: Dec;
  odds_decimal: Dec;
  captured_at: Iso;
  minutes_to_ko: number;
  source: "prematch" | "live";
  is_validated_close: boolean;
  close_validation_method: string | null;
}

export interface ConsensusQuote {
  market_key: string;
  selection: string;
  line: Dec;
  as_of: Iso;
  devig_method: string;
  p_fair: Dec;
  n_bookmakers: number;
  overround: Dec;
  best_odds: Dec;
  best_bookmaker: string;
  dispersion: Dec | null;
}

export interface HistoricalPrice {
  selection: string;
  odds_decimal: Dec;
  raw_implied: Dec;
}

export interface HistoricalBook {
  bookmaker_code: string;
  /** The source's own label. No timestamp exists for either kind. */
  price_kind: "closing" | "pre_closing";
  market_key: string;
  line: Dec;
  overround: Dec | null;
  is_composite: boolean;
  prices: HistoricalPrice[];
}

export interface HistoricalFair {
  bookmaker_code: string;
  price_kind: "closing" | "pre_closing";
  devig_method: string;
  p_home: Dec;
  p_draw: Dec;
  p_away: Dec;
  overround: Dec;
}

export interface HistoricalMarket {
  source: string;
  note: string;
  books: HistoricalBook[];
  fair_1x2: HistoricalFair[];
}

export interface FixtureOdds {
  match: MatchSummary;
  board: Section<MarketQuote[]>;
  series: Section<OddsSeries[]>;
  near_close: Section<NearCloseQuote[]>;
  consensus: Section<ConsensusQuote[]>;
  /** Prices from a second source (Football-Data.co.uk), kept apart from what we captured. */
  historical: Section<HistoricalMarket | null>;
}

export interface BookmakerMargin {
  bookmaker_code: string;
  price_kind: string;
  market_key: string;
  fixtures: number;
  mean_overround: Dec;
  median_overround: Dec;
  best_price_share: Dec | null;
}

export interface MovementRow {
  competition_id: number;
  competition: string;
  season: number;
  fixtures: number;
  mean_abs_home_shift: Dec;
  favourite_shortened_share: Dec;
  pre_closing_logloss: Dec;
  closing_logloss: Dec;
}

export interface OddsIntelligence {
  source: string;
  note: string;
  fixtures_with_prices: number;
  seasons: number[];
  margins: Section<BookmakerMargin[]>;
  movement: Section<MovementRow[]>;
  live: Section<Record<string, number>>;
}

export type ComponentStatus = "ok" | "degraded" | "down" | "unknown";

export interface ComponentHealth {
  status: ComponentStatus;
  detail: string;
  data: Record<string, unknown>;
}

export interface SystemHealth {
  status: ComponentStatus;
  checked_at: Iso;
  app: ComponentHealth;
  database: ComponentHealth;
  worker: ComponentHealth;
  football_provider: ComponentHealth;
}

export interface DatabaseStats {
  revision: string;
  competitions_known: number;
  competitions_tracked: number;
  teams: number;
  fixtures: number;
  fixtures_with_result: number;
  odds_snapshots: number;
  near_close_snapshots: number;
  bookmakers: number;
  markets_tracked: number;
  raw_payloads: number;
  predictions: number;
  picks: number;
}

export interface WorkerState {
  alive: boolean | null;
  last_beat_at: Iso | null;
  started_at: Iso | null;
  ticks: number | null;
  last_tick_outcome: string | null;
  scheduler_lag_ms: number | null;
  code_version: string | null;
  next_runs: Record<string, string | null>;
}

export interface ProviderState {
  provider: string;
  plan: string;
  requests_today: number;
  daily_budget: number;
  requests_remaining: number;
  plan_daily_limit: number;
  last_error: string | null;
  last_error_at: Iso | null;
}

export interface FixtureCounts {
  upcoming_24h: number;
  upcoming_7d: number;
  awaiting_result: number;
  finished: number;
  finished_with_result: number;
  next_fixture: MatchSummary | null;
}

export interface Freshness {
  last_payload_at: Iso | null;
  last_fixtures_sync_at: Iso | null;
  last_results_sync_at: Iso | null;
  last_odds_capture_at: Iso | null;
  last_snapshot_at: Iso | null;
}

export interface Overview {
  system: SystemHealth;
  database: DatabaseStats;
  worker: WorkerState;
  provider: ProviderState;
  fixtures: FixtureCounts;
  freshness: Freshness;
  recent_runs: RunSummary[];
  picks: Section<Record<string, number> | null>;
  performance: Section<null>;
}

/** The quality snapshot as the API returns it; ratios are null when there is no denominator. */
export interface QualitySnapshot {
  computed_at: Iso;
  horizon_hours: number;
  fixtures_expected: number;
  fixtures_with_odds: number;
  fixtures_with_near_close: number;
  bookmakers_active: number;
  bookmakers_seen_24h: number;
  markets_tracked: number;
  markets_seen_24h: number;
  snapshots_24h: number;
  stale_fixtures: number;
  failed_jobs_24h: number;
  partial_jobs_24h: number;
  provider_errors_24h: number;
  /** Runs stopped at their planned request cap ("aborted"): not failures. */
  capped_jobs_24h?: number;
  /** Runs whose process ended first (restart, deadline), closed by the run watchdog. */
  interrupted_jobs_24h?: number;
  /** Runs closed by the run watchdog past their deadline. */
  stale_jobs_24h?: number;
  requests_today: number;
  ledger_api_calls_today: number;
  daily_budget: number;
  requests_remaining_today: number;
  unattributed_requests_today: number;
  stale_running_jobs: number;
  fixtures_awaiting_result: number;
  fixtures_with_result: number;
  last_successful_capture: Iso | null;
  windows_expected_24h: number;
  windows_captured_24h: number;
  notes: string[];
  fixture_odds_coverage: number | null;
  bookmaker_coverage: number | null;
  market_coverage: number | null;
  window_coverage_24h: number | null;
}

export interface QualityReport {
  snapshot: QualitySnapshot;
  explanations: Record<string, string>;
}

export interface CoverageRow {
  competition_id: number;
  competition: string;
  season: number;
  fixtures_in_horizon: number;
  fixtures_with_odds: number;
  odds_coverage: number | null;
  bookmakers_seen_24h: number;
  markets_seen_24h: number;
  last_capture_at: Iso | null;
  fixtures_awaiting_result: number;
}

export interface QualityIssue {
  key: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  count: number;
  detected_at: Iso;
}

export interface CalibrationBucket {
  lower: number;
  upper: number;
  n: number;
  mean_predicted: number | null;
  observed_rate: number | null;
}

export interface ScoreSummary {
  n: number;
  brier: number;
  log_loss: number;
  ece: number;
}

export type Verdict = "worse" | "indistinguishable" | "better";

/** Model minus market on the fixtures BOTH priced. Negative = the model scored better. */
export interface MarketComparison {
  baseline_key: string;
  market_key: string;
  line: Dec;
  n_common: number;
  model_logloss: Dec;
  baseline_logloss: Dec;
  logloss_diff: Dec;
  logloss_diff_ci_low: Dec;
  logloss_diff_ci_high: Dec;
  model_brier: Dec;
  baseline_brier: Dec;
  brier_diff: Dec;
  brier_diff_ci_low: Dec;
  brier_diff_ci_high: Dec;
  verdict: Verdict;
}

export interface SplitRow {
  key: string;
  label: string;
  n: number;
  model_logloss: number;
  baseline_logloss: number;
  logloss_diff: number;
}

export interface Coverage {
  targets: number;
  predicted: number;
  uncovered: Record<string, number>;
  fits: number;
  failed_fits: number;
  no_interval: number;
}

export interface HypotheticalBetting {
  hypothetical: true;
  rule: string;
  odds_source: string;
  fixtures_priced: number;
  n_bets: number;
  staked_units: Dec;
  profit_units: Dec;
  roi_pct: Dec | null;
  roi_ci_low: Dec | null;
  roi_ci_high: Dec | null;
  max_drawdown_units: Dec | null;
  mean_probability_edge: number | null;
  note: string;
}

export interface BacktestMetrics {
  run_id: number;
  name: string;
  protocol: string;
  session_id: number | null;
  test_from: string;
  test_to: string;
  n_samples: number;
  brier: Dec;
  logloss: Dec;
  ece: Dec;
  /** Reported because the table has it. Never used to rank a model. */
  accuracy_pct: Dec;
  coverage: Coverage | null;
  primary: MarketComparison | null;
  vs_market: MarketComparison[];
  calibration: CalibrationBucket[];
  over_under_2_5: ScoreSummary | null;
  btts: ScoreSummary | null;
  by_competition: SplitRow[];
  by_month: SplitRow[];
  betting: HypotheticalBetting | null;
  odds_source: string | null;
  n_bets: number | null;
  roi_pct: Dec | null;
  yield_pct: Dec | null;
  near_close_lv_mean: Dec | null;
  code_version: string;
  finished_at: Iso | null;
}

export interface ModelVersionSummary {
  model_id: number;
  name: string;
  family: string;
  description: string;
  version_id: number;
  version: string;
  status: string;
  hyperparameters: Record<string, unknown>;
  train_from: string;
  train_to: string;
  n_train: number;
  code_version: string;
  created_at: Iso;
  latest_backtest: BacktestMetrics | null;
}

export interface MarketBaselineSummary {
  fixtures_with_consensus: number;
  methods: string[];
  last_as_of: Iso | null;
}

export interface BaselineScore {
  baseline_key: string;
  source: string;
  bookmaker_code: string;
  /** As the SOURCE labels it ('closing', 'pre_closing'); not our capture. */
  price_kind: string;
  devig_method: string;
  market_key: string;
  line: Dec;
  n_samples: number;
  brier: Dec;
  logloss: Dec;
  ece: Dec;
  mean_overround: Dec | null;
  is_primary: boolean;
}

export interface BacktestSessionSummary {
  id: number;
  session_uuid: string;
  name: string;
  protocol: string;
  competitions: { id: number; name: string }[];
  validation_season: number | null;
  test_season: number;
  test_from: string;
  test_to: string;
  n_targets: number;
  primary_baseline: string;
  dataset_hash: string;
  code_version: string;
  finished_at: Iso | null;
  selection: Record<string, SelectionInfo>;
  config: Record<string, unknown>;
}

export interface SelectionInfo {
  chosen: { xi: number; penalty: number };
  /** Every candidate's validation score. A session stores it only since the
   * grid search was recorded; an older session carries the choice alone. */
  validation_logloss?: Record<string, number>;
  initial_grid?: { xi: number[]; penalty: number[] };
  final_grid?: { xi: number[]; penalty: number[] };
  validation_season?: number;
}

export interface ModelsOverview {
  market_baseline: Section<MarketBaselineSummary | null>;
  backtest: Section<BacktestSessionSummary | null>;
  historical_baselines: Section<BaselineScore[]>;
  models: Section<ModelVersionSummary[]>;
}

export interface PickEvent {
  from_status: string | null;
  to_status: string;
  at: Iso;
  reason: string;
}

export type PickStatus = "shadow" | "qualified" | "published" | "settled";

/** A shadow pick with everything it claims traced to where it came from. */
export interface PickRow {
  id: number;
  fixture_id: number;
  fixture: string;
  competition: string;
  kickoff_at: Iso;
  market_key: string;
  selection: string;
  line: Dec;
  status: PickStatus;
  mode: string;
  model: string;
  model_version: string;
  prediction_id: number | null;
  data_cutoff_ts: Iso;
  feature_set_hash: string;
  /** False: the model's own probability, no calibrator applied. */
  calibrated: boolean;
  bookmaker: string;
  market_odds: Dec;
  odds_captured_at: Iso;
  odds_payload_hash: string | null;
  p_model: Dec;
  p_lo: Dec | null;
  p_hi: Dec | null;
  p_market_fair: Dec;
  consensus_method: string | null;
  consensus_as_of: Iso | null;
  fair_odds: Dec;
  probability_edge: Dec;
  price_edge: Dec;
  ev: Dec;
  ev_at_lower_bound: Dec | null;
  kelly_fraction: Dec;
  stake_units: Dec;
  stake_policy: string;
  decision_rule_version: string;
  code_version: string;
  qualification: { qualified?: boolean; reasons?: string[]; evidence?: Record<string, unknown> };
  result_status: string;
  profit_units: Dec | null;
  settled_at: Iso | null;
  settlement_basis: string | null;
  review_reason: string | null;
  created_at: Iso;
  events: PickEvent[];
}

export interface CandidateRow {
  id: number;
  fixture_id: number;
  fixture: string;
  market_key: string;
  selection: string;
  line: Dec;
  model: string;
  bookmaker: string | null;
  market_odds: Dec | null;
  p_model: Dec;
  p_market_fair: Dec | null;
  probability_edge: Dec | null;
  ev: Dec | null;
  decision: "selected" | "rejected";
  rejection_reason: string | null;
  decision_rule_version: string | null;
  odds_captured_at: Iso | null;
  evaluated_at: Iso;
}

export interface Lifecycle {
  candidates: number;
  rejected: number;
  shadow: number;
  qualified: number;
  published: number;
  settled: number;
}

export interface PicksOverview {
  lifecycle: Lifecycle;
  rule: Record<string, unknown>;
  rejection_reasons: Record<string, number>;
  publishing_enabled: false;
  candidates_by_decision: Record<string, number>;
  picks_by_mode: Record<string, number>;
  picks: Section<PickRow[]>;
  recent_candidates: Section<CandidateRow[]>;
}

export interface PerformanceSlice {
  dimension: "market" | "model" | "rule" | "month" | "odds_band";
  key: string;
  settled: number;
  staked_units: Dec | null;
  profit_units: Dec | null;
  roi_pct: Dec | null;
  roi_ci95_pct: Dec | null;
  hit_rate: Dec | null;
  mean_odds: Dec | null;
  expected_profit_units: Dec | null;
}

export interface PerformanceSummary {
  settled: number;
  pending: number;
  staked_units: Dec | null;
  profit_units: Dec | null;
  roi_pct: Dec | null;
  hit_rate: Dec | null;
  note: string;
  slices: PerformanceSlice[];
}

export interface SearchHit {
  type: "fixture" | "team" | "competition";
  id: number;
  label: string;
  sublabel: string;
}

export interface ToolSpec {
  name: string;
  description: string;
  parameters: {
    type: string;
    properties?: Record<string, { type: string; description?: string }>;
    required?: string[];
  };
  endpoint: string;
}

export interface AnalystStatus {
  configured: boolean;
  /** Environment variables still to set on the API host. Never values. */
  missing: string[];
  tools: ToolSpec[];
  rules: string[];
}

export interface ToolResult {
  tool: string;
  arguments: Record<string, unknown>;
  status: DataStatus | null;
  reason: string | null;
  data: unknown;
  provenance: { endpoint: string; generated_at: Iso; data_as_of: Iso | null; read_only: boolean };
}

export interface Citation {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  status: string | null;
  provenance: ToolResult["provenance"] | null;
  error: string | null;
}

export interface AnalystReply {
  text: string;
  citations: Citation[];
  /** Numbers in the answer that no tool result contains. */
  unverified_figures: string[];
  rounds: number;
  stopped: string | null;
}

export interface NotificationRow {
  id: number;
  kind: string;
  title: string;
  body: string;
  created_at: Iso;
  channel: string | null;
  status: "queued" | "sent" | "skipped" | "failed";
  attempts: number;
  sent_at: Iso | null;
  last_error: string | null;
}

export interface NotificationsOverview {
  channel_configured: boolean;
  by_status: Record<string, number>;
  recent: NotificationRow[];
}

export interface RatingRow {
  rank: number;
  team_id: number;
  team: string;
  rating: number;
  matches: number;
  last_match_at: Iso;
  last_competition: string;
  change_last5: number | null;
  /** Fewer than 10 rated matches: still mostly the starting value. */
  provisional: boolean;
}

export interface Rankings {
  elo_version: string;
  run_id: number;
  computed_at: Iso;
  parameters: string;
  rows: RatingRow[];
}

export interface JobHealth {
  job_type: string;
  runs_24h: number;
  failed_24h: number;
  partial_24h: number;
  api_calls_24h: number;
  last_status: string | null;
  last_started_at: Iso | null;
  last_success_at: Iso | null;
  last_error: string | null;
  mean_duration_ms: number | null;
  /** From the worker's last heartbeat; null for manual jobs. */
  next_run_at: Iso | null;
}

// ---------------------------------------------------------------------------
// Match Center -> Audit (GET /matches/{id}/audit)
// ---------------------------------------------------------------------------

export type AuditScalar = string | number | boolean | null;
export type AuditStepKey =
  | "provider"
  | "raw"
  | "normalized"
  | "features"
  | "models"
  | "predictions"
  | "market"
  | "picks"
  | "settlement";
export type AuditStepState = "recorded" | "partial" | "missing" | "not_applicable";

export interface AuditItem {
  kind: string;
  ref: string;
  at: Iso | null;
  source: string | null;
  facts: Record<string, AuditScalar>;
  /** "kind:ref" of the records this one was computed from. */
  links: string[];
}

export interface AuditTrailStep {
  key: AuditStepKey;
  label: string;
  state: AuditStepState;
  detail: string;
  items: AuditItem[];
}

export interface MatchAudit {
  fixture_id: number;
  provider_fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  steps: AuditTrailStep[];
  /** Every step is recorded or not applicable: nothing expected is missing. */
  complete: boolean;
}

// ---------------------------------------------------------------------------
// Analytics page (GET /analytics/*)
// ---------------------------------------------------------------------------

export interface CompetitionProfile {
  competition_id: number;
  competition: string;
  country: string | null;
  competition_type: string;
  season: number;
  fixtures: number;
  finished: number;
  low_sample: boolean;
  home_win: number | null;
  draw: number | null;
  away_win: number | null;
  goals_per_match: number | null;
  home_goals_per_match: number | null;
  away_goals_per_match: number | null;
  home_goal_difference: number | null;
  btts: number | null;
  over_2_5: number | null;
  with_team_stats: number;
  with_historical_odds: number;
  with_odds_snapshots: number;
  with_features: number;
  with_predictions: number;
}

export interface EloPoint {
  fixture_id: number;
  kickoff_at: Iso;
  competition: string;
  opponent: TeamRef;
  at_home: boolean;
  rating_before: number;
  rating_after: number;
  expected_score: number;
  actual_score: number;
}

export interface RecordSplit {
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  points_per_match: number | null;
}

export interface ProcessPoint {
  fixture_id: number;
  kickoff_at: Iso;
  source: string;
  shots_for: number | null;
  shots_against: number | null;
  shots_on_target_for: number | null;
  shots_on_target_against: number | null;
}

export interface TeamFeatures {
  fixture_id: number;
  feature_version: string;
  data_cutoff: Iso;
  side: string;
  values: Record<string, number | null>;
}

export interface TeamAnalytics {
  team: TeamRef;
  splits: Record<"all" | "home" | "away", RecordSplit>;
  elo: EloPoint[];
  process: ProcessPoint[];
  features: TeamFeatures | null;
}

export interface MarketBucket {
  lower: number;
  upper: number;
  n: number;
  mean_probability: number | null;
  observed_rate: number | null;
}

export interface MarketSeason {
  competition_id: number;
  competition: string;
  season: number;
  n: number;
  closing_logloss: number | null;
  pre_closing_logloss: number | null;
  closing_improvement: number | null;
  mean_overround_closing: number | null;
}

export interface MarketAnalytics {
  baseline: string;
  n_fixtures: number;
  calibration: MarketBucket[];
  by_season: MarketSeason[];
  source: string;
}

export interface GateCheck {
  name: string;
  passed: boolean;
  evidence: string;
}

export interface ExperimentSummary {
  id: number;
  uuid: string;
  name: string;
  model_family: string;
  research_status: "RESEARCH" | "CANDIDATE" | "PRODUCTION" | "RETIRED";
  gate_passed: boolean;
  gate: GateCheck[];
  reproduced: boolean;
  reproduced_by: number | null;
  reproduction_of: number | null;
  backtest_session_id: number | null;
  code_version: string;
  dataset_hash: string | null;
  feature_version: string | null;
  test_from: string | null;
  test_to: string | null;
  own_n: number | null;
  own_logloss: number | null;
  own_brier: number | null;
  own_ece: number | null;
  market_logloss_diff: number | null;
  market_diff_low: number | null;
  market_diff_high: number | null;
  verdict: string | null;
  evidence: string | null;
  dm_p: number | null;
  by_competition: Array<Record<string, number | string>>;
  finished_at: Iso | null;
}

export interface CoverageCell {
  competition_id: number;
  competition: string;
  season: number;
  fixtures: number;
  finished: number;
  with_result: number;
  with_team_stats: number;
  with_events: number;
  with_lineups: number;
  with_player_stats: number;
  with_historical_odds: number;
  with_odds_snapshots: number;
  with_features: number;
  with_predictions: number;
}

export interface MigrationProgress {
  plan_id: number | null;
  plan_name: string | null;
  plan_created_at: Iso | null;
  planned_requests: number | null;
  units: Record<string, Record<string, number>>;
  requests_spent: number;
  rows_written: number;
  by_tier: Record<string, Record<string, number>>;
  last_activity_at: Iso | null;
}
