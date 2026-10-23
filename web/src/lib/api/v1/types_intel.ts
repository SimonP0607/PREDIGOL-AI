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
    h2h: {
      n: number;
      /** The size the meetings' weights leave (Kish); absent in a dossier built before dossier-v4. */
      n_effective?: number;
      relevance: string;
      note: string;
      last_days_ago: Num;
    };
    /** The observable tactics of each side (plan F6); absent in a dossier built before dossier-v5. */
    tactics?: IntelTacticsBlock;
  } | null;
  /** The weighted head-to-head, as the AI's packet carries it (packet-v8); null when the packet has none. */
  h2h: IntelH2hBlock | null;
  /** What the match alone does to its table and to its tie; null when there is nothing to say. */
  scenarios: IntelScenariosBlock | null;
  /** The status of each context factor AS THE AI SAW IT at the packet's moment. */
  factors: IntelFactorsBlock | null;
  narrative: Array<{ key: string; title: string; text: string | null }> | null;
  narrative_engine: "llm" | "rules" | null;
  /** The latest brief: what the AI said, what it asked the server to look into, every claim the server refused. */
  brief: IntelBrief | null;
  /** The latest passes of the match (newest first) and what each did about the research the brief asked for. */
  passes: IntelPass[];
  decisions: Array<Record<string, unknown>>;
}

// ── PLAN F6 · the AI's side of a match ───────────────────────────────────────────────────────────────────────

/** The statuses of a context factor: DESCRIPTIVE until a person validates it with an experiment. */
export type IntelFactorStatus = "DESCRIPTIVE" | "VALIDATED";
export type IntelPassKind = "first" | "pre" | "final" | "request";

/** A row of the dossier's picker: GET /api/v1/admin/intelligence/matches. */
export interface IntelPickerRow {
  fixture_id: number;
  kickoff_at: string;
  status_short: string | null;
  home: string;
  away: string;
  competition: string;
  country: string | null;
  /** The moment of the newest packet the AI built for the match; null when it never studied it. */
  packet_as_of: string | null;
  brief_pass: IntelPassKind | null;
  brief_escalate: boolean | null;
  /** How many pieces of research the newest brief asked for (0 when it asked none or there is no brief). */
  research_asked: number;
}

export interface IntelPicker {
  /** "day": the matches of a Bogotá day; "search": the matches a text names within 45 days of that day. */
  mode: "day" | "search";
  day: string;
  q: string | null;
  /** Day mode: every match of the day (the list may be cut by the limit). Search mode: the matches found. */
  total: number;
  with_packet: number;
  matches: IntelPickerRow[];
}

export type IntelMeetingScope = "same_competition" | "same_kind" | "other_official" | "friendly";
export type IntelMeetingGround = "home" | "away" | "neutral";

/** The raw record of the meetings in regulation time, from the point of view of the match's home side. */
export interface IntelH2hRecord {
  n: number;
  home_side_wins: number;
  draws: number;
  away_side_wins: number;
}

export interface IntelH2hMeeting {
  fixture_id: number;
  days_ago: number;
  competition: string;
  scope: IntelMeetingScope;
  home_side_was: IntelMeetingGround;
  goals_home_side: number;
  goals_away_side: number;
  after_extra_time: boolean;
  coach_changed: { home: boolean | null; away: boolean | null };
  /** What the meeting weighs for THIS match (0..1): recency x competition x ground x coaches. */
  weight: number;
}

export interface IntelH2hBlock {
  version: string;
  status: IntelFactorStatus | string;
  n: number;
  n_effective: number;
  last_days_ago: number | null;
  relevance: string;
  note: string;
  oldest_days_ago?: number;
  record?: IntelH2hRecord;
  weighted?: {
    home_side_win: number;
    draw: number;
    away_side_win: number;
    goals_home_side_pg: number;
    goals_away_side_pg: number;
  } | null;
  same_venue?: IntelH2hRecord | null;
  coaches?: { both_same: number; some_changed: number; unknown: number };
  meetings?: IntelH2hMeeting[];
  weights?: Record<string, unknown>;
  weights_note?: string;
}

export interface IntelScenarioSide {
  points: number;
  rank_best: number;
  rank_worst: number;
  zones: Array<{ description: string | null; kind: string | null }>;
}

export type IntelScenarioResult = "home_win" | "draw" | "away_win";

export interface IntelScenarioTable {
  version: string;
  group: string | null;
  snapshot_at: string | null;
  /** Set when the table's ranks are not the order of its points: nothing is read from it. */
  unavailable?: string;
  basis?: string;
  teams?: number;
  home?: {
    team_id: number;
    rank_now: number;
    points_now: number;
    played: number;
    zone_now: string | null;
  };
  away?: {
    team_id: number;
    rank_now: number;
    points_now: number;
    played: number;
    zone_now: string | null;
  };
  after?: Record<IntelScenarioResult, { home: IntelScenarioSide; away: IntelScenarioSide }>;
}

export interface IntelTieSide {
  ahead_if_margin_at_least: number;
  level_if_margin: number;
  behind_if_margin_at_most: number;
  can_lose_by_up_to: number | null;
  needs_to_win_by_at_least: number | null;
}

export interface IntelScenarioTie {
  version: string;
  kind: string;
  aggregate?: string;
  note?: string;
  aggregate_before?: { home_side: number; away_side: number };
  lead_home_side?: number;
  margin?: string;
  home_side?: IntelTieSide;
  away_side?: IntelTieSide;
  if_level?: string;
  /** A series (best of N) or a replay: the games played so far, as the server states them. */
  game?: number;
  wins_home_side?: number;
  wins_away_side?: number;
  draws?: number;
  complete?: boolean;
  decides_the_tie?: boolean;
}

export interface IntelScenariosBlock {
  version: string;
  status: IntelFactorStatus | string;
  table: IntelScenarioTable | null;
  tie: IntelScenarioTie | null;
  note: string;
}

/** One factor as the packet states it. */
export interface IntelFactorEntry {
  version: string;
  block: string;
  status: IntelFactorStatus | string;
  decision: { id: number; decided_at: string; experiment: string | null } | null;
}

/** The packet's `factors` block: a version, a note, perhaps an error, and one entry per factor of the catalogue. */
export interface IntelFactorsBlock {
  version: string;
  note: string;
  error?: string;
  [factor: string]: IntelFactorEntry | string | undefined;
}

export interface IntelTacticsProfile {
  team_id: number;
  /** Matches read (last ten within 400 days). */
  n: number;
  data?: {
    sheets: {
      none: number;
      crossed: number;
      without_formation: number;
      without_the_eleven: number;
    };
    events: { none: number; inconsistent: number };
  };
  formations?: {
    n: number;
    main?: string;
    main_count?: number;
    last?: string;
    distinct?: number;
    changes?: number;
    counts?: Record<string, number>;
  };
  starters?: { n: number; pairs?: number; avg_changes?: number | null; ever_present?: number };
  coach?: { n: number; distinct?: number; newest_matches?: number };
  goals?: {
    n: number;
    bands?: string[];
    for?: number[];
    against?: number[];
    total_for?: number;
    total_against?: number;
    late?: { for: number; against: number; matches_for: number; matches_against: number };
  };
  with_the_score?: {
    n: number;
    half_time: {
      n: number;
      leading: IntelTally;
      level: IntelTally;
      trailing: IntelTally;
    };
    scored_first?: IntelTally;
    conceded_first?: IntelTally;
    goalless?: number;
    led_and_did_not_win?: number;
    trailed_and_did_not_lose?: number;
  };
  substitutions?: {
    n: number;
    with_substitutions?: number;
    per_match?: number | null;
    first_minute?: { mean: number | null; median: number | null };
    first_by_state?: Record<string, { n: number; mean_minute: number | null }>;
  };
}

export interface IntelTally {
  n: number;
  wins: number;
  draws: number;
  losses: number;
}

export interface IntelTacticsBlock {
  version: string;
  status: IntelFactorStatus | string;
  note: string;
  home: IntelTacticsProfile;
  away: IntelTacticsProfile;
}

/** What the AI asked the server to look into (`fbi.ai.research`): a topic and a side from the server's lists, and a reason. */
export interface IntelResearchAsk {
  topic: "availability" | "confirmation" | "preview" | (string & {});
  side: "home" | "away" | "both" | (string & {});
  why: { text?: string; type?: string; refs?: string[] };
}

/** A claim the server refused, and why. */
export interface IntelRefusedClaim {
  group: string;
  text: string;
  why: string;
}

export interface IntelBrief {
  id: number;
  created_at: string;
  pass: IntelPassKind;
  version: string;
  engine: "llm" | "rules";
  model: string | null;
  status: string;
  summary: string | null;
  escalate: boolean;
  reasons: string[];
  uncertainty: "low" | "medium" | "high" | null;
  data_quality: "good" | "fair" | "poor" | null;
  cost_usd: number;
  research: IntelResearchAsk[];
  refused: IntelRefusedClaim[];
  /** All the claims refused; `refused` lists the first forty. */
  refused_total: number;
}

/** What a pass did about the research the brief of its match asked for. */
export interface IntelResearchCounts {
  /** The brief written in this pass asked for research. */
  requested: number;
  /** Requests the pass found in the previous brief. */
  asked: number;
  /** Requests it served (the web was read for them). */
  searched: number;
  /** Requests it did not serve, by reason (no_allowance, near_budget, pass_budget, no_search_pass). */
  unserved: Record<string, number>;
  web_searches: number;
}

export interface IntelPass {
  pass: Exclude<IntelPassKind, "request">;
  day: string;
  status: "ok" | "partial" | "skipped" | "failed" | (string & {});
  started_at: string;
  finished_at: string;
  escalated: boolean;
  reasons: string[];
  cost_usd: number;
  note: string | null;
  research: IntelResearchCounts;
}

/** The registry of context factors: GET /api/v1/admin/intelligence/factors. */
export interface IntelFactorDecision {
  id: number;
  version: string;
  status: IntelFactorStatus;
  decided_at: string;
  decided_by: string;
  who: string | null;
  reason: string;
  experiment: string | null;
  previous_id: number | null;
}

export interface IntelFactorRow {
  key: string;
  label: string;
  /** What an experiment would have to show for the factor to be validated (Spanish, for the owner). */
  claim: string;
  version: string;
  block: string;
  status: IntelFactorStatus;
  decision: { id: number; decided_at: string; experiment: string | null } | null;
  /** Every decision taken about the factor (any version), newest first. */
  decisions: IntelFactorDecision[];
}

export interface IntelFactorsRegistry {
  version: string;
  note: string;
  factors: IntelFactorRow[];
}

export interface IntelCalibration {
  champions: IntelCalibrationRow[];
  fits: Array<Record<string, unknown>>;
  promotions: Array<Record<string, unknown>>;
  evaluations: Array<Record<string, unknown>>;
  gates: Record<string, unknown>;
}

/** What a row of the memory rests on, newest first, a sample of at most 40 ids per kind (memory-v4; null before it). */
export interface IntelEvidenceRef {
  decisions?: number[];
  postmortems?: number[];
  fixtures?: number[];
}

export interface IntelMemoryRow {
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  aspect: string;
  as_of_day: string;
  /** The version of the memory that wrote the row (memory-v4 is the one with confidence and evidence). */
  version: string;
  stats: Record<string, unknown>;
  delta: Record<string, unknown>;
  /** The effective sample over itself plus a constant, 0 to 1; null for a row an older version wrote. */
  confidence: number | null;
  evidence_ref: IntelEvidenceRef | null;
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

/**
 * The price clock (plan F1): /api/v1/admin/intelligence/price-clock. The prices the provider returned before
 * kick-off, structured from the RAW /odds bodies; this view only reports how far that structuring has got.
 * Per-bet and per-family counts are null when the server could not count them in the time it allows itself.
 */
export type IntelClockStatus = "ok" | "empty" | "no_fixture" | "after_kickoff" | "error";

export interface IntelClockLedgerRow {
  status: IntelClockStatus | string;
  version: string;
  payloads: number;
  quotes: number;
  refused: number;
  last: string | null;
}

export interface IntelClockFamily {
  key: string;
  label: string;
  bets: number;
  extracted: number;
  quotes: Num;
}

export interface IntelClockBet {
  bet_id: number;
  name: string;
  family: string;
  period: string;
  subject: string;
  status: IntelMarketRow["status"];
  schema: string;
  quotes: Num;
  last: string | null;
}

export interface IntelClockIssue {
  payload: string;
  provider_fixture_id: number | null;
  status: IntelClockStatus | string;
  detail: string | null;
  quotes_refused: number;
  extracted_at: string;
}

export interface IntelClockRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  rows_written: Num;
  errors: Num;
  last_error: string | null;
  notes: string | null;
}

export interface IntelPriceClock {
  extractor: string;
  raw: { payloads: number; first: string | null; last: string | null };
  backlog: number;
  ledger: IntelClockLedgerRow[];
  quotes: {
    first?: string | null;
    last?: string | null;
    fixtures?: Num;
    quotes?: Num;
    gigabytes: number;
  };
  families: IntelClockFamily[];
  bets: IntelClockBet[];
  unclassified: Array<{ bet_id: number; name: string; classified_at: string }>;
  issues: IntelClockIssue[];
  runs: IntelClockRun[];
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
