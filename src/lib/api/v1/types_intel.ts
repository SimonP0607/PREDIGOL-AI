/** PrediGol Intelligence (Admin Console): /api/v1/admin/intelligence/*. Numbers arrive as numbers, instants as ISO
 * text; every block may be absent on a young database. */

export type IntelState =
  | "RECHAZADO"
  | "INVESTIGACION"
  | "CAUTELA"
  | "APROBADO"
  | "PICK_DEL_DIA"
  | "CANDIDATO_PARLAY"
  | "PICK_PREMIUM";
export type IntelContext = "FULL" | "PARTIAL" | "LIMITED" | "PENDING" | "AI_OFF";
export type IntelMarket = "1X2" | "OU" | "BTTS" | "DC" | "AH";
export type Num = number | null | undefined;

export interface IntelDecisionRow {
  id: number;
  known_at: string;
  checkpoint: string;
  fixture_id: number;
  kickoff_at: string;
  match: string;
  competition: string;
  country?: string | null;
  market_key: string;
  selection: string;
  line: Num;
  model_name: string;
  odds: Num;
  n_bookmakers?: Num;
  p_model: Num;
  p_cal: Num;
  p_market: Num;
  ev_raw?: Num;
  ev_cal: Num;
  edge_cal?: Num;
  state: IntelState;
  reasons: string[];
  premium?: boolean;
  parlay_eligible?: boolean;
  score: Num;
  stake_units: Num;
  context_status: IntelContext;
  review?: string | null;
  result_status?: string | null;
  profit_flat?: Num;
  clv?: Num;
}

export interface IntelCalibrationRow {
  market_key: string;
  model_name: string;
  role: string;
  since: string;
  method: string;
  params?: Record<string, number>;
  known_at?: string;
  n_train?: number;
  logloss_cal?: string | number | null;
  logloss_raw?: string | number | null;
  logloss_market?: string | number | null;
  ece?: string | number | null;
  n_oos?: string | number | null;
  days_oos?: string | number | null;
  rule_clv?: string | number | null;
  rule_n?: string | number | null;
  edge?: string | null;
}

export interface IntelRun {
  id: number;
  job: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  duration_ms: number | null;
  counts: Record<string, unknown>;
  errors: string[];
  code_version?: string | null;
}

export interface IntelSelection {
  kind: "pick" | "parlay";
  rank: number;
  odds: Num;
  p_est: Num;
  ev: Num;
  stake_units: Num;
  selected_at: string;
  decision_ids: number[];
  detail: Record<string, unknown>;
  correlation?: Record<string, unknown>;
}

export interface IntelDay {
  day: string;
  fixtures: { fixtures?: number; with_candidates?: number };
  decisions: {
    by_state: Partial<Record<IntelState, number>>;
    by_context: Partial<Record<IntelContext, number>>;
    total: number;
  };
  depth: {
    passes: Array<{
      pass: string;
      n: number;
      web: Num;
      l2: Num;
      l3: Num;
      marginal_saved: Num;
      cost_usd: Num;
    }>;
    briefs: { briefs?: number; llm?: number; with_narrative?: number };
  };
  usage: Array<{
    purpose: string;
    tier: string;
    calls: number;
    usd: Num;
    tokens_in: Num;
    tokens_out: Num;
  }>;
  cost_usd: number;
  tokens: { in: number; out: number };
  sources: Array<{ origin: string; status: string; source_tier: string; n: number }>;
  selections_v6: IntelSelection[];
  daily_set_v5: Array<{
    rank: number;
    fixture_id: number;
    match: string;
    market_key: string;
    selection: string;
    line: Num;
    odds: Num;
    p_model: Num;
    p_market: Num;
    ev: Num;
    status: string;
    profit_units: Num;
  }>;
  report: {
    revision: number;
    built_at: string;
    text: string;
    content: Record<string, unknown>;
  } | null;
  runs: IntelRun[];
  calibration: IntelCalibrationRow[];
}

export interface IntelFilter {
  n: number;
  key: string;
  ok: boolean | null;
  why: string;
  effect?: string;
  data?: Record<string, unknown>;
}

export interface IntelScoreComponent {
  key: string;
  weight: number;
  value: number | null;
  points: number;
  detail: string;
}

export interface IntelDecisionDetail {
  decision: Record<string, unknown> & {
    id: number;
    match: string;
    competition: string;
    market_key: string;
    selection: string;
    line: Num;
    state: IntelState;
    filters: IntelFilter[];
    score_components: IntelScoreComponent[] | null;
    stake_components: Record<string, unknown> | null;
    context: Record<string, unknown>;
    reasons: string[];
  };
  pick: Record<string, unknown> | null;
  calibrator: Record<string, unknown> | null;
  review: Record<string, unknown> | null;
  evidence: Array<Record<string, unknown>>;
  outcome: Record<string, unknown> | null;
  postmortem: Record<string, unknown> | null;
  history: Array<Record<string, unknown>>;
  cost: Record<string, unknown> | null;
}

export interface IntelTeamBlock {
  n: number;
  wins?: number;
  draws?: number;
  losses?: number;
  goals_for?: Num;
  goals_against?: Num;
  xg_for?: Num;
  xg_against?: Num;
  shots?: Num;
  shots_against?: Num;
  sot?: Num;
  sot_against?: Num;
  corners?: Num;
  corners_against?: Num;
  fouls?: Num;
  fouls_against?: Num;
  cards?: Num;
  offsides?: Num;
  possession?: Num;
  penalties_for?: number;
  penalties_against?: number;
  clean_sheets?: number;
  btts?: number;
  over_2_5?: number;
}

export interface IntelTeamProfile {
  n: number;
  all?: IntelTeamBlock;
  home?: IntelTeamBlock;
  away?: IntelTeamBlock;
  results?: string;
  streaks?: { unbeaten: number; winless: number; scoring: number; conceding: number };
  scoreline?: {
    n: number;
    scored_first: number;
    won_after_scoring_first: number;
    leads_lost: number;
    comebacks: number;
  };
  opponents?: { n: number; mean_elo: Num };
  coach?: {
    name: string | null;
    main_formation: string | null;
    formations: Record<string, number>;
    rotation_avg_changes: Num;
    first_sub_minute: Num;
  };
}

export interface IntelPlayer {
  id: number;
  name: string;
  apps: number;
  starts: number;
  minutes: number;
  goals: number;
  assists: number;
  shots: number;
  cards: number;
  rating: Num;
  minutes_14d: number;
  reported_out: string | null;
}

export interface IntelDossier {
  fixture: {
    id: number;
    kickoff_at: string;
    status_short: string;
    home: string;
    away: string;
    competition: string;
  };
  packet: { id: number; version: string; as_of: string; missing: string[] } | null;
  dossier: {
    version: string;
    teams: { home: IntelTeamProfile; away: IntelTeamProfile };
    players: { home: IntelPlayer[]; away: IntelPlayer[] };
    referee: Record<string, unknown>;
    context: Record<string, unknown>;
    h2h: { n: number; relevance: string; note: string; last_days_ago: Num };
  } | null;
  narrative: Array<{ key: string; title: string; text: string | null }> | null;
  narrative_engine: "llm" | "rules" | null;
  brief: Record<string, unknown> | null;
  decisions: Array<Record<string, unknown>>;
}

export interface IntelCalibration {
  champions: IntelCalibrationRow[];
  fits: Array<Record<string, unknown>>;
  promotions: Array<Record<string, unknown>>;
  evaluations: Array<Record<string, unknown>>;
  gates: Record<string, unknown>;
}

export interface IntelMemoryRow {
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  aspect: string;
  as_of_day: string;
  stats: Record<string, unknown>;
  delta: Record<string, unknown>;
}

export interface IntelMarketRow {
  provider_bet_id: number;
  name: string;
  market_key: string | null;
  status: "ACTIVE" | "RESEARCH" | "CANDIDATE" | "NOT_MODELABLE";
  criteria: Record<string, { ok: boolean; value: unknown }>;
  metrics: Record<string, unknown>;
  proposal: string | null;
}

export interface IntelCosts {
  total_7d_usd: number;
  per_day_usd: number;
  per_match_usd: Num;
  per_candidate_usd: Num;
  per_pick_usd: Num;
  per_research_usd: Num;
  per_postmortem_usd: Num;
  budget?: Record<string, unknown>;
  projection?: Record<string, unknown>;
  alerts?: Array<{ threshold: number; at: string; spent_usd: number; budget_usd: number }>;
  thresholds?: number[];
  monthly_budget_usd: number;
}
