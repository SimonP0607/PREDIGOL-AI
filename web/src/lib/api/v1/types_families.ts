/**
 * The families in shadow (plan F10.17 and F11.11): /api/v1/admin/intelligence/families. Corners, cards and the goals of the halves decide in SHADOW
 * under a version of their own (`decision-fam-v1`), and this is the one place they are read: the last word of each family on each match, the rule
 * that grades it, what became of it, the post-mortem the families made of it and what they remember. Reading only; SUPER_ADMIN only.
 * Numbers arrive as numbers, instants as ISO text; every block may be empty on a young database (the switch is off until the owner asks).
 */

export type FamilyCode = "CORNERS" | "CARDS" | "YELLOW" | "GOALS_HALF";
/** A family's state is capped at research: INVESTIGACION (a selection being measured) or RECHAZADO (the filters refused it). */
export type FamilyState = "INVESTIGACION" | "RECHAZADO";
export type FamilyResult = "win" | "loss" | "push" | "void" | "half_win" | "half_loss";
export type FamilyVerdict = "MERECIDO" | "VARIANZA" | "SUERTE" | "ERROR" | "NULO" | "SIN_DATOS";
export type FamilyQuality = "GOOD" | "NEUTRAL" | "BAD" | "UNKNOWN";
export type FamilyStep = "families" | "family_outcomes" | "family_postmortems" | "family_memory";
export type FamilyEntityType = "family" | "market" | "competition" | "referee";

/** The versions of each stage of the cycle of a family: the forecast, the decision, its settlement, its post-mortem and the memory. */
export interface FamiliesVersions {
  forecast: string;
  decision: string;
  outcome: string;
  postmortem: string;
  memory: string;
}

/** The last time a step of the cycle ran, and what it reported (the counts differ by step). */
export interface FamiliesStepRun {
  step: FamilyStep | string;
  job: string;
  run_id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  ms: number | null;
  result: Record<string, unknown>;
  /** What the step raised in that run (`step: Type: message`), or null when it did not raise. */
  error: string | null;
}

/** What a bet is graded ON: one measure of the finished match, read in one convention (`fbi.market.rules`). */
export interface FamiliesRule {
  key: string;
  measure: string;
  version: number;
  period: "FT" | "1H" | "2H" | string;
  /** The registry's own words, in English. */
  convention: string;
  columns: string[];
  liquidable: boolean;
  note: string;
}

export interface FamiliesCard {
  family: FamilyCode | string;
  /** Last words that are selections (INVESTIGACION), those the filters refused, and the selections settled and still open. */
  selections: number;
  rejected: number;
  settled: number;
  open: number;
  results: Partial<Record<FamilyResult, number>>;
  verdicts: Partial<Record<FamilyVerdict, number>>;
  /** The keys of the rules (in `IntelFamilies.rules`) that grade the bets of the family. */
  rules: string[];
  /** The newest snapshot of the memory of the family, or null while it has none. */
  memory: FamiliesMemoryRow | null;
}

export interface FamiliesOutcome {
  result: FamilyResult | string;
  profit_flat: number | null;
  close_odds: number | null;
  close_p_fair: number | null;
  close_minutes_to_ko: number | null;
  clv: number | null;
}

export interface FamiliesPostmortem {
  verdict: FamilyVerdict | string;
  quality: FamilyQuality | string;
  /** The causes the post-mortem found, as the owner reads them (Spanish, as stored). */
  causes: string[];
  /** The count the line was graded on, and by how much it passed the line (none for a bet on two counts). */
  actual: number | null;
  margin: number | null;
}

/** The last word of one family's model on one market of one match. */
export interface FamiliesItem {
  id: number;
  fixture_id: number;
  kickoff_at: string;
  known_at: string;
  checkpoint: string;
  match: string;
  home: string;
  away: string;
  competition: string;
  country: string | null;
  family: FamilyCode | string;
  model_name: string;
  market_key: string;
  selection: string;
  line: number | null;
  odds: number | null;
  n_bookmakers: number | null;
  /** What the family stated: its own number, not calibrated. */
  p_model: number | null;
  /** What the books' consensus said at the decision. */
  p_market: number | null;
  ev_raw: number | null;
  state: FamilyState | string;
  stake_units: number | null;
  reasons: string[];
  /** How many times the decision was written for this model and market of this match (the last one is shown). */
  revisions: number;
  forecast: {
    forecast_id: number | null;
    known_at: string | null;
    calibration: string | null;
  } | null;
  /** The key of the rule (in `rules`) that grades the bet, or null when no rule can. */
  rule: string | null;
  outcome: FamiliesOutcome | null;
  postmortem: FamiliesPostmortem | null;
}

/** The record of a set of post-mortems (`memory-fam-v1`): every key is always there, a zero or null. */
export interface FamiliesRecord {
  n: number;
  decided: number;
  wins: number;
  hit: number | null;
  claimed: number | null;
  gap: number | null;
  z: number | null;
  clv_n: number;
  clv_mean: number | null;
  quality: Partial<Record<FamilyQuality, number>>;
  staked: number;
  profit: number;
  roi: number | null;
  verdicts: Partial<Record<FamilyVerdict, number>>;
  results: Partial<Record<FamilyResult, number>>;
}

export interface FamiliesMemoryStats {
  all: FamiliesRecord;
  recent: FamiliesRecord;
  recent_days: number;
  /** Only the memory of a family: the same record by model. */
  models?: Record<string, FamiliesRecord>;
}

export interface FamiliesMemoryRow {
  entity_type: FamilyEntityType | string;
  entity_key: string;
  entity_name: string | null;
  version: string;
  as_of_day: string;
  built_at: string;
  /** From 0 to 1: how much of the record rests on enough recent evidence. */
  confidence: number | null;
  stats: FamiliesMemoryStats;
  /** The recent record minus the one over everything, for what both have. */
  delta: Record<string, number>;
  evidence_ref: {
    postmortems?: number;
    n_eff?: number;
    from_kickoff?: string;
    to_kickoff?: string;
    through?: { id: number; created_at: string };
  } & Record<string, unknown>;
}

export interface IntelFamilies {
  versions: FamiliesVersions;
  window: { days: number; from: string; to: string };
  /** What the worker did in its latest run of a step of the families: `shadow`, `off`, or null when it has never run one. */
  mode: string | null;
  steps: FamiliesStepRun[];
  families: FamiliesCard[];
  /** The last words matching the filter, newest match first, and how many there were in all. */
  items: FamiliesItem[];
  total: number;
  rules: Record<string, FamiliesRule>;
  memory: FamiliesMemoryRow[];
}
