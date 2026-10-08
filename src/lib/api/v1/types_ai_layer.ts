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
  daily_budget_usd: string;
  monthly_budget_usd: string;
  ratio: number;
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

export interface EvolutionDashboard {
  day: string;
  counts: Record<string, number>;
  findings: AiMemoryEvent[];
  errors: EvolutionError[];
  shadow: ShadowReportRow[];
  cost_usd: Dec;
}
