/**
 * The AI decision layer (fbi.ai), as the API returns it: the per-match analysis users read and the Admin
 * Console's views. Mirrors fbi.api.contracts.ai_layer. Nothing here can change a pick: a review only
 * confirms, lowers, rejects or abstains, and only the owner's switch AND a passed shadow gate let it filter.
 */
import type { Dec, Iso } from "./types";

export type AiDecision = "APPROVE" | "DOWNGRADE" | "REJECT" | "ABSTAIN";
export type CardVerdict = "recommended" | "caution" | "not_recommended" | "no_market";
export type CardKind = "value" | "evaluated" | "no_market";
export type AiMode = "off" | "shadow" | "enforce";
export type ClaimType = "DATA" | "INFERENCE" | "NEWS" | "OPINION" | "UNKNOWN";

export interface AiClaim {
  text: string;
  type: ClaimType | string;
  code?: string | null;
  params?: Record<string, unknown> | null;
  refs?: string[];
}

export interface CardAi {
  decision: AiDecision;
  review_id: number | null;
  confidence: number | null;
  reason: string | null;
  positives: AiClaim[];
  risks: AiClaim[];
  engines: string[];
}

export interface CardNotes {
  why: AiClaim[];
  risks: AiClaim[];
}

export interface AnalysisCard {
  market: string;
  selection: string;
  line: Dec;
  kind: CardKind;
  odds: Dec | null;
  bookmaker: string | null;
  p_model: Dec | null;
  p_low: Dec | null;
  p_market: Dec | null;
  fair_odds: Dec | null;
  /** The lowest price worth taking at the model's pessimistic probability. */
  minimum_odds: Dec | null;
  edge: Dec | null;
  ev: Dec | null;
  model: string | null;
  qualified: boolean;
  verdict: CardVerdict;
  verdict_reason: string;
  ai: CardAi | null;
  /** The L1 brief's "why" and "what could go wrong" for this card (the owner's view, or enforced). */
  notes?: CardNotes | null;
}

export type EscalationReason =
  | "candidate"
  | "model_market_gap"
  | "market_move"
  | "important_news"
  | "high_uncertainty"
  | "contradiction"
  | "brief_flag";

/** L1: the economical model's (or the rules') reading of a match of the day. Never a probability. */
export interface BriefView {
  id: number;
  created_at: Iso;
  pass_kind: string;
  engine: "llm" | "rules";
  model: string | null;
  status: string;
  escalate: boolean;
  reasons: EscalationReason[] | string[];
  uncertainty: "low" | "medium" | "high" | null;
  data_quality: "good" | "fair" | "poor" | null;
  summary: string | null;
  context: AiClaim[];
  injuries: Array<{ side: "home" | "away"; player: string; status: string; refs?: string[] }>;
  changes: AiClaim[];
}

export interface MatchAnalysis {
  fixture_id: number;
  built_at: Iso | null;
  audience: "user" | "evaluation";
  mode: AiMode;
  /** True only when the owner enabled enforcement AND the AI's shadow gate passed. */
  enforced: boolean;
  market_observed: boolean;
  engines: string[];
  /** A language model reviewed at least one selection of this match. */
  analyzed_by_llm: boolean;
  cards: AnalysisCard[];
  /** Cards a user does not see: their pick is in evaluation (shadow). */
  withheld: number;
  missing: string[];
  /** The L1 brief (the owner's view, or enforced). */
  brief?: BriefView | null;
  /** The newest of the analysis and its brief. */
  updated_at?: Iso | null;
  /** A match of today with a market: the AI works on it. */
  in_ai_day?: boolean;
}

export interface AiTierView {
  provider: string;
  model: string;
  key_present: boolean;
}

export interface AiCycleRow {
  id: number;
  kind: string;
  started_at: Iso;
  finished_at: Iso | null;
  status: string;
  mode: string;
  budget_state: string;
  counts: Record<string, number>;
  cost_usd: Dec;
  error: string | null;
}

export interface AiBudgetView {
  state: "NORMAL" | "REDUCED" | "CHEAP_ONLY" | "EXHAUSTED";
  spent_today_usd: string;
  spent_month_usd: string;
  /** Today's adaptive budget (pace left in the month x the day's load). */
  daily_budget_usd: string;
  monthly_budget_usd: string;
  ratio: number;
  /** Today's ceiling (EXHAUSTED there). */
  daily_cap_usd?: string;
  /** The owner's soft daily target. */
  daily_target_usd?: string;
  remaining_month_usd?: string;
  pace_usd?: string;
  load?: number;
  days_left?: number;
  month_ratio?: number;
  day?: string | null;
}

export interface AiProjection {
  run_rate_usd: number;
  projected_today_usd: number;
  projected_month_usd: number;
  monthly_budget_usd: number;
  projected_share: number | null;
  days_in_month: number;
  days_left: number;
  last_days: Array<{ day: string; cost_usd: number }>;
}

export interface AiBudgetAlert {
  month: string;
  threshold: 70 | 85 | 95 | 100 | number;
  at: Iso;
  spent_usd: number;
  budget_usd: number;
}

export interface AiStackRow {
  level: "L1" | "L2" | "L3" | "web";
  tier: string;
  role: string;
  provider: string | null;
  model: string | null;
  configured: boolean;
}

export interface AiEfficiency {
  day: string;
  matches_today: number;
  with_market: number;
  analyzed: number;
  briefs_llm: number;
  briefs_rules: number;
  escalated: number;
  intermediate: number;
  deep: number;
  candidates: number;
  approved: number;
  caution: number;
  rejected: number;
  abstained: number;
  searches: number;
  news: number;
  cost_usd: number;
  cost_per_match: number | null;
  cost_per_candidate: number | null;
  cost_per_approved: number | null;
}

export interface AiDayPlan {
  day: string;
  stages: Record<
    string,
    {
      created_at: Iso;
      fixtures_total: number;
      fixtures_with_market: number;
      budget: Partial<AiBudgetView>;
      notes: Record<string, unknown>;
    }
  >;
}

export interface AiSettingsView {
  mode: AiMode;
  llm_configured: boolean;
  tiers: Record<"bulk" | "analysis" | "final", AiTierView | null>;
  missing: string[];
  daily_budget_usd: string;
  monthly_budget_usd: string;
  max_llm_reviews_per_day: number;
  max_deep_per_day: number;
  daily_target_usd?: string;
  daily_max_factor?: string;
  max_web_first?: number;
  max_web_pre?: number;
  max_watch_per_day?: number;
  multimodal: boolean;
  horizon_hours: number;
  search: string | null;
  search_configured: boolean;
}

export interface ShadowGateCheck {
  value: unknown;
  need: unknown;
  ok: boolean;
}

export interface ShadowArm {
  n: number;
  fixtures?: number;
  hit_rate?: number | null;
  roi?: number;
  profit?: number;
  ev_claimed?: number;
  ev_market?: number | null;
  clv?: number | null;
  n_clv?: number;
  logloss_model?: number | null;
  logloss_market?: number | null;
  brier_model?: number | null;
  brier_market?: number | null;
  ece_model?: number | null;
  ece_market?: number | null;
  max_drawdown?: number;
}

export interface ShadowReportRow {
  engine: "rules" | "llm" | "combined";
  created_at: Iso;
  window_from: string;
  window_to: string;
  verdict: "pass" | "fail" | "insufficient" | null;
  checks: Record<string, ShadowGateCheck> | null;
  arms: Record<string, ShadowArm>;
}

export interface AiOverview {
  settings: AiSettingsView;
  budget: AiBudgetView;
  enforcement: { enforced: boolean; reason: string; gate_verdict: string | null };
  last_cycles: AiCycleRow[];
  today: Record<string, number>;
  shadow: ShadowReportRow[];
  projection?: AiProjection;
  alerts?: AiBudgetAlert[];
  /** The configured models per level and the search API - read from the configuration. */
  stack?: AiStackRow[];
  efficiency?: AiEfficiency;
  day?: AiDayPlan | null;
}

export interface AiReviewRow {
  id: number;
  reviewed_at: Iso;
  fixture_id: number;
  match: string;
  kickoff_at: Iso;
  competition: string;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec | null;
  p_model: Dec | null;
  p_market: Dec | null;
  edge: Dec | null;
  decision: AiDecision;
  confidence: Dec;
  engine: "rules" | "llm" | "combined";
  engine_version: string;
  model: string | null;
  reason: string | null;
  status: string;
  mode: string;
  cost_usd: Dec;
}

export interface AiUsageRow {
  id: number;
  at: Iso;
  purpose: string;
  tier: string;
  provider: string;
  model: string;
  prompt_version: string | null;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  searches: number;
  cost_usd: Dec;
  latency_ms: number | null;
  status: string;
  error: string | null;
}

export interface AiReviewDetail {
  review: AiReviewRow;
  output: Record<string, unknown> & {
    positive_evidence?: AiClaim[];
    negative_evidence?: AiClaim[];
    uncertainties?: AiClaim[];
    contradictions?: AiClaim[];
    rejected_claims?: Array<{ group: string; text: string; why: string }>;
    reason?: string;
    engines?: Array<{ engine: string; decision: string; review_id: number | null; status: string }>;
  };
  sources: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  packet: {
    id: number;
    packet_hash: string;
    as_of: Iso;
    approx_tokens: number;
    missing: string[];
    content: Record<string, unknown>;
  } | null;
  components: AiReviewRow[];
  usage: AiUsageRow[];
  input_hash: string;
}

export interface AiPacketView {
  id: number;
  fixture_id: number;
  packet_version: string;
  as_of: Iso;
  built_at: Iso;
  packet_hash: string;
  approx_tokens: number;
  missing: string[];
  content: Record<string, unknown>;
  sources: Array<Record<string, unknown>>;
  history: Array<{
    id: number;
    as_of: Iso;
    packet_hash: string;
    approx_tokens: number;
    missing: string[];
  }>;
}

export type EvidenceStatus = "CONFIRMED" | "PROBABLE" | "RUMOR" | "CONTRADICTORY" | "OUTDATED";

export interface AiEvidenceRow {
  id: number;
  fixture_id: number | null;
  match: string | null;
  team: string | null;
  kind: string;
  claim: string;
  origin: "provider" | "web" | "owner";
  source_name: string;
  source_url: string | null;
  source_tier: string;
  published_at: Iso | null;
  retrieved_at: Iso;
  status: EvidenceStatus;
  status_reason: string;
  status_history: Array<Record<string, unknown>>;
  attributes: Record<string, unknown>;
}

export interface AiMemoryEvent {
  id: number;
  created_at: Iso;
  kind: string;
  entity_type: string;
  entity_id: string;
  fixture_id: number | null;
  hypothesis: string | null;
  evidence: Record<string, unknown>;
  result: string | null;
  confidence: Dec | null;
  version: string;
}

export interface AiCostPeriod {
  since: Iso;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  searches: number;
  vision: number;
  failed: number;
  cost_usd: number;
  legacy_cost_usd: number;
  fixtures: number;
  llm_reviews: number;
  reviews: number;
  approved_with_llm: number;
  cost_per_match: number | null;
  cost_per_review: number | null;
  cost_per_approved: number | null;
  briefs?: number;
  selected?: number;
  cost_per_analysis?: number | null;
  cost_per_search?: number | null;
  cost_per_selected?: number | null;
  by_level?: Array<{ key: string; tier: string; requests: number; cost_usd: number }>;
  by_purpose: Array<{ key: string; requests: number; cost_usd: number }>;
  by_model: Array<{
    key: string;
    requests: number;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
  }>;
}

export interface AiSimulation {
  profile: string;
  note: string;
  per_day: Record<string, number>;
  day_usd: number;
  month_usd: number;
  per_match_usd: number | null;
  per_review_usd: number | null;
}

export interface AiCosts {
  periods: Record<"today" | "7d" | "30d" | "month", AiCostPeriod>;
  budget: AiBudgetView;
  projection?: AiProjection;
  alerts?: AiBudgetAlert[];
  thresholds?: number[];
  workload: Record<string, unknown>;
  simulation: AiSimulation[];
  worst_case: AiSimulation[];
}

export interface AiRunRequest {
  id: number;
  kind: "analysis" | "learning";
  fixture_id: number | null;
  requested_at: Iso;
  status: "queued" | "running" | "done" | "failed";
  picked_at: Iso | null;
  cycle_id: number | null;
  finished_at: Iso | null;
  cycle_status: string | null;
  counts: Record<string, number> | null;
  cost_usd: number | null;
  error: string | null;
}

export interface AiRunQueued {
  id: number;
  kind: string;
  status: string;
  requested_at: Iso;
}

export interface EvolutionError {
  fixture_id: number;
  match: string;
  kickoff_at: Iso;
  /** Regulation score [home, away]. */
  score: number[] | null;
  market: string | null;
  selection: string | null;
  line: string | null;
  decision: AiDecision | null;
  settled: string | null;
  p_model: number | null;
  p_market: number | null;
  signals: string[];
  narrative: string | null;
}

export interface LearningNote {
  id: number;
  day: string;
  created_at: Iso;
  kind:
    | "summary"
    | "approved"
    | "rejected"
    | "context"
    | "news"
    | "injuries"
    | "market"
    | "model"
    | "sources"
    | "lesson"
    | string;
  title: string;
  body: string;
  n: number;
  evidence: Record<string, unknown>;
  engine: "rules" | "llm" | string;
}

export interface Proposal {
  id: number;
  created_at: Iso;
  title: string;
  hypothesis: string;
  rationale: string | null;
  target: string;
  status: "PROPOSED" | "INVESTIGATING" | string;
  proposed_by: string;
  n_matches: number | null;
  impact: string | null;
  investigation_cost: string | null;
  evidence: Record<string, unknown>;
}

export interface EvolutionDashboard {
  day: string;
  counts: Record<string, number>;
  findings: AiMemoryEvent[];
  errors: EvolutionError[];
  shadow: ShadowReportRow[];
  cost_usd: Dec;
  /** QUÉ APRENDIÓ PREDIGOL HOY. */
  learned?: LearningNote[];
  /** MEJORAS PROPUESTAS awaiting the owner. */
  proposals?: Proposal[];
}

export interface AiPassRow {
  pass: "first" | "pre" | "final";
  at: Iso;
  status: string;
  escalated: boolean;
  reasons: string[];
  counts: Record<string, number>;
  cost_usd: number;
}

export interface AiDayBrief {
  id: number;
  created_at: Iso;
  pass: string;
  engine: "llm" | "rules";
  model: string | null;
  status: string;
  escalate: boolean;
  reasons: string[];
  uncertainty: string | null;
  data_quality: string | null;
  summary: string | null;
  injuries: Array<{ side: string; player: string; status: string }>;
  changes: AiClaim[];
  context: AiClaim[];
}

export interface AiDaySelection {
  review_id: number;
  market: string;
  selection: string;
  line: string;
  odds: number | null;
  p_model: number | null;
  p_market: number | null;
  edge: number | null;
  decision: AiDecision;
  by_llm: boolean;
  model: string | null;
  reason: string | null;
  reviewed_at: Iso;
}

export interface AiDayFixture {
  fixture_id: number;
  match: string;
  competition: string;
  kickoff_at: Iso;
  has_market: boolean;
  odds_age_minutes: number | null;
  priority: number;
  important: boolean;
  passes: AiPassRow[];
  brief: AiDayBrief | null;
  selections: AiDaySelection[];
  cost_usd: number;
}

export interface AiToday {
  day: string;
  plan: AiDayPlan | null;
  fixtures: AiDayFixture[];
  without_market: number;
  totals: {
    with_market: number;
    passes: number;
    escalated: number;
    stale_odds: number;
    cost_usd: number;
  };
}

export interface AiResearchEvidence {
  id: number;
  kind: string;
  claim: string;
  origin: "provider" | "web" | "owner";
  team: string | null;
  source: string;
  url: string | null;
  domain: string | null;
  tier: string;
  published_at: Iso | null;
  retrieved_at: Iso;
  last_seen_at: Iso | null;
  seen_count: number;
  status: EvidenceStatus;
  status_reason: string;
  confidence: number;
  relevance: number;
  title: string | null;
  player: string | null;
}

export interface AiResearchRow {
  fixture_id: number;
  match: string;
  kickoff_at: Iso;
  searches: Array<{ at: Iso; status: string; cost_usd: number; error: string | null }>;
  evidence: AiResearchEvidence[];
  cost_usd: number;
}

export type LossClass =
  | "MODEL_ERROR"
  | "CONTEXT_ERROR"
  | "DATA_ERROR"
  | "MARKET_ERROR"
  | "EXECUTION_ERROR"
  | "NORMAL_VARIANCE"
  | "UNKNOWN";

export type PostmortemVerdict =
  | "approved_won"
  | "approved_lost"
  | "caution_won"
  | "caution_lost"
  | "rejected_would_have_won"
  | "rejected_correctly"
  | "unreviewed_won"
  | "unreviewed_lost"
  | "push";

export interface PostmortemAnswer {
  answer: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface PickPostmortem {
  id: number;
  fixture_id: number;
  match: string;
  competition: string | null;
  kickoff_at: Iso;
  market_key: string;
  selection: string;
  line: Dec;
  roles: string[];
  decision: AiDecision | null;
  settled: string;
  verdict: PostmortemVerdict;
  classification: LossClass | null;
  odds: Dec | null;
  close_odds: Dec | null;
  clv: Dec | null;
  p_model: Dec | null;
  p_market: Dec | null;
  /** The ten questions: expected, happened, model, information, ignored_signal, odds_moved, key_absence,
   * lineup_changed, uncertainty, variance. */
  answers: Record<string, PostmortemAnswer>;
  narrative: string | null;
  created_at: Iso;
}

export interface AiLearning {
  day: string;
  notes: LearningNote[];
  proposals: Proposal[];
}

export interface AiSourceRow {
  domain: string;
  tier: string;
  results: number;
  evidence: number;
  useful: number;
  discarded: number;
  cost_usd: number;
  utility: number | null;
}

export interface AiComparisonRow {
  arm: "model" | "model_rules" | "model_ai" | "market";
  label: string;
  n: number;
  logloss: number | null;
  brier: number | null;
  ece: number | null;
  roi: number | null;
  clv: number | null;
  ev_claimed: number | null;
  ev_market: number | null;
  hit_rate: number | null;
  max_drawdown: number | null;
}

export interface AiComparison {
  rows: AiComparisonRow[];
  window_from: string | null;
  window_to: string | null;
  verdict: string | null;
  sample: Record<string, unknown>;
  shadow: boolean;
}

// ── CIERRE DEL DÍA (fbi.ai.daily_review) ────────────────────────────────────

export interface DailyReviewItem {
  rank: number;
  fixture_id: number;
  match: string;
  market: string;
  selection: string;
  line: number;
  odds: number;
  model: string | null;
  status: string;
  profit_units: number | null;
  /** The AI's last pre-match decision on it. */
  ai_last: AiDecision | null;
  near_close_odds: number | null;
  phase: string;
}

export interface DailyReviewPicks {
  source: "evaluation" | "qualified";
  set_status: string | null;
  n: number;
  won: number;
  lost: number;
  void: number;
  pending: number;
  pnl_units: number;
  staked_units: number;
  roi: number | null;
  /** Mean odds taken / the same bookmaker's last pre-match price - 1. */
  line_value: number | null;
  items: DailyReviewItem[];
}

export interface DailyReviewMarket {
  market: string;
  n: number;
  settled: number;
  won: number;
  roi: number | null;
  line_value: number | null;
  line_value_devigged: number | null;
  ev_claimed: number | null;
  p_model: number | null;
  p_market: number | null;
}

export interface DailyReviewContent {
  day: string;
  timezone: string;
  matches: {
    tracked: number;
    with_market: number;
    analysed_by_ai: number;
    played: number;
    not_played: number;
    still_to_finish: number;
  };
  daily_picks: DailyReviewPicks;
  qualified_picks: DailyReviewPicks;
  shadow: {
    selections: number;
    settled: number;
    won: number;
    pnl_units: number;
    roi: number | null;
    by_market: DailyReviewMarket[];
  };
  /** reviewed, approve, downgrade, reject, abstain and <decision>_won / <decision>_lost. */
  ai: Record<string, number>;
  postmortems: {
    n: number;
    by_class: Record<string, number>;
    by_verdict: Record<string, number>;
    /** Wins judged against the close: EARNED, LUCKY, UNKNOWN. */
    wins_by_quality?: Record<string, number>;
  };
  learning: { kind: string; title: string; n: number | null }[];
  patterns: { kind: string; about: string; text: string | null }[];
  hypotheses: {
    new: number;
    new_titles: string[];
    rejected: number;
    investigating: number;
    validated: number;
    promoted: number;
    waiting_owner_at_end: number;
  };
  experiments: { started: number; finished: number; running_at_end: number };
  costs: { ai_usd: number; by_purpose: Record<string, number>; api_football_requests: number };
  settlement: {
    matches: number;
    median_seconds: number | null;
    max_seconds: number | null;
    by_path: Record<string, number>;
  };
  pending_fixtures: number[];
  waiting_human: number[];
}

export interface DailyReviewRevision {
  revision: number;
  kind: "close" | "update";
  built_at: Iso;
  complete: boolean;
  pending_fixtures: number[];
}

export interface DailyReview {
  day: string;
  revision: number;
  kind: "close" | "update";
  built_at: Iso;
  complete: boolean;
  content: DailyReviewContent;
  revisions: DailyReviewRevision[];
}

export interface DailyReviewDay {
  day: string;
  revisions: number;
  built_at: Iso;
  complete: boolean;
  matches: number;
  played: number;
  daily_won: number;
  daily_lost: number;
  daily_pending: number;
  daily_pnl_units: number;
  shadow_roi: number | null;
  ai_usd: number;
}

// ── MATCH INTELLIGENCE MEMORY ───────────────────────────────────────────────

export interface MemoryFilters {
  team?: string | undefined;
  competition?: string | undefined;
  coach?: string | undefined;
  player?: string | undefined;
  market?: string | undefined;
  odds_band?: string | undefined;
  model?: string | undefined;
}

export interface MatchMemory {
  fixture_id: number;
  kickoff_at: Iso;
  status_short: string;
  competition: string;
  home: string;
  away: string;
  home_coach: string | null;
  away_coach: string | null;
  score_home: number | null;
  score_away: number | null;
  /** BEFORE: the AI's newest brief before kick-off. */
  brief_summary: string | null;
  brief_quality: string | null;
  brief_uncertainty: string | null;
  ai_decisions: Record<string, number>;
  selections: number;
  markets: string[];
  models: string[];
  /** AFTER. */
  won: number;
  lost: number;
  pnl_units: number | null;
  postmortem_classes: Record<string, number>;
  win_quality: Record<string, number>;
  memory_events: number;
}
