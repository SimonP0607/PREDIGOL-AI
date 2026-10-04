/**
 * Types for the product's records: the day's picks and parlays as persisted (GET /daily),
 * a user's own picks and parlays (/me/picks, /me/parlays) and their history (/me/history).
 * Mirrors fbi.api.contracts.records.
 */
import type { Dec, Iso } from "./types";
import type { CompetitionBadge, TeamBadge } from "./types_product";

export type ResultStatus = "PENDING" | "WIN" | "LOSS" | "PUSH" | "VOID" | "HALF_WIN" | "HALF_LOSS";
export type ParlayStatus =
  "BUILDING" | "READY" | "ACTIVE" | "WON" | "LOST" | "VOID" | "PARTIAL_VOID";
export type SetSource = "qualified" | "evaluation";
export type Stage = "T-24h" | "T-12h" | "T-6h" | "T-3h";

export interface MatchRef {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  /** Regulation score, once the match has one. */
  score_home: number | null;
  score_away: number | null;
}

export interface DailyItem {
  rank: number;
  pick_id: number;
  match: MatchRef;
  market_key: string;
  selection: string;
  line: Dec;
  stage: Stage;
  selected_at: Iso;
  /** The price frozen when the pick entered the set. */
  odds: Dec;
  bookmaker: string | null;
  price_at: Iso;
  p_model: Dec;
  p_low: Dec;
  p_market: Dec;
  ev: Dec;
  model: string | null;
  status: ResultStatus;
  profit_units: Dec | null;
  settled_at: Iso | null;
}

export interface DailySet {
  id: number;
  day: string;
  timezone: string;
  source: SetSource;
  rule_version: string;
  status: "BUILDING" | "COMPLETE" | "SETTLED";
  items: DailyItem[];
}

export interface ParlayRecordLeg {
  leg_no: number;
  pick_id: number;
  match: MatchRef;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec;
  bookmaker: string | null;
  p_model: Dec;
  p_low: Dec;
  p_market: Dec;
  ev: Dec;
  status: ResultStatus;
}

export type RecordKind = "daily" | "multiday";

export interface ParlayRecord {
  id: number;
  kind: RecordKind;
  day: string;
  source: SetSource;
  rule_version: string;
  status: ParlayStatus;
  min_legs: number;
  max_legs: number;
  window_from: Iso;
  window_to: Iso;
  combined_odds: Dec | null;
  /** Probability every leg wins, at each leg's pessimistic probability. */
  p_all_low: Dec | null;
  /** Of a 1% stake, at the pessimistic probabilities. */
  expected_log_growth: Dec | null;
  ready_at: Iso | null;
  settled_at: Iso | null;
  profit_units: Dec | null;
  legs: ParlayRecordLeg[];
}

export interface DailyBoard {
  day: string;
  timezone: string;
  source: SetSource;
  /** The owner's preview of the evaluation records: nothing here is a recommendation. */
  evaluation_mode: boolean;
  set: DailySet | null;
  daily_parlay: ParlayRecord | null;
  multiday_parlay: ParlayRecord | null;
  /** no_qualified_picks | no_shadow_picks, when the set has no item. */
  reason: string | null;
}

export type MarketKey = "1X2" | "OU" | "BTTS" | "AH" | "DC";

export interface SavePickIn {
  fixture_id: number;
  market_key: MarketKey;
  selection: string;
  line?: string | number;
  /** Set when the selection is one of PrediGol's picks. */
  pick_id?: number | null;
  /** The price the user got at their own bookmaker. */
  user_odds?: string | number | null;
}

export interface PickSnapshot {
  saved_at: string;
  price: {
    odds: string;
    bookmaker: string | null;
    as_of: string;
    p_fair: string;
    n_bookmakers: number;
  } | null;
  pick: {
    id: number;
    status: string;
    model: string;
    p_model: string;
    p_low: string | null;
    ev: string;
  } | null;
}

export interface UserPick {
  id: number;
  match: MatchRef;
  market_key: string;
  selection: string;
  line: Dec;
  origin: "predigol_pick" | "market";
  pick_id: number | null;
  odds: Dec | null;
  bookmaker: string | null;
  price_at: Iso | null;
  user_odds: Dec | null;
  saved_at: Iso;
  status: ResultStatus;
  profit_units: Dec | null;
  settled_at: Iso | null;
  snapshot: PickSnapshot;
}

export interface LegIn {
  fixture_id: number;
  market_key: MarketKey;
  selection: string;
  line?: string | number;
  odds?: string | number | null;
}

export interface ParlayIn {
  name?: string | null;
  legs: LegIn[];
}

export interface ValidationIssue {
  code: string;
  leg?: number;
  with?: number;
  min?: number;
  max?: number;
  got?: number;
}

export interface ParlayValidation {
  ok: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  legs: Array<{
    leg: number;
    fixture_id: number;
    market_key: string;
    selection: string;
    line: string;
    odds?: string | null;
    kickoff_at?: string;
    price?: { odds: string; bookmaker: string | null; as_of: string } | null;
  }>;
  combined_odds: Dec | null;
}

export interface UserParlayLeg {
  leg_no: number;
  match: MatchRef;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec | null;
  status: ResultStatus;
}

export interface UserParlay {
  id: number;
  name: string | null;
  created_at: Iso;
  combined_odds: Dec | null;
  status: ParlayStatus;
  profit_units: Dec | null;
  settled_at: Iso | null;
  warnings: ValidationIssue[];
  legs: UserParlayLeg[];
}

export type HistoryPeriod = "today" | "7d" | "30d" | "all";
export type HistoryGroupKey = "predigol_picks" | "my_picks" | "predigol_parlays" | "my_parlays";

export interface HistoryGroup {
  total: number;
  pending: number;
  won: number;
  lost: number;
  push: number;
  void: number;
  hit_rate: number | null;
  staked_units: Dec;
  profit_units: Dec;
  roi: number | null;
}

export interface History {
  period: HistoryPeriod;
  timezone: string;
  since: Iso;
  until: Iso;
  evaluation_mode: boolean;
  groups: Record<HistoryGroupKey, HistoryGroup>;
}
