/**
 * C-13 «Perfil estadístico» and C-14 «Probabilidades por mercado» (plan EA; backend `fbi.api.contracts.intelligence.
 * stats_profile` and `market_probs`). Precomputed history and sealed probabilities: the page draws, it never recomputes.
 * C-13 1.1.0 (plan PM, PM-05-05): `provider_extras` of a team and a player - figures as API-Football measured them («dato de
 * API-Football»), empty while `FBI_STATS_PROVIDER_EXTRAS` is off. No component reads them yet.
 */
import type { ContractHead, ItemList, Maybe, MarketState, Probability } from "./types_intelligence";

export type StatsScope = "u5" | "u10" | "u20" | "season";
export type StatsContext = "all" | "home" | "away";
export type TrendContext = StatsContext | "favorite";
export type Better = "mas" | "menos" | "neutral";
export type StatUnit = "por_partido" | "por_90" | "porcentaje";
export type PositionGroup = "portero" | "defensa" | "medio" | "delantero";
export type RadarKey = "ataque" | "pegada" | "volumen" | "presencia" | "defensa" | "disciplina";
export type EntityRole = "perfil" | "local" | "visitante" | "a" | "b";

export interface Ref {
  id: number;
  name: string;
}

export interface CompetitionSeasonRef {
  competition_season_id: number;
  competition: Ref;
  season: number;
  country: Maybe<string>;
}

export interface Quantiles {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  entities: number;
}

export interface StatFigure {
  key: string;
  unit: StatUnit;
  better: Better;
  value: Maybe<number>;
  matches_with_data: number;
  percentile: Maybe<number>;
  league_value: Maybe<number>;
  distribution: Maybe<Quantiles>;
}

/** C-13 1.1.0: a figure as the provider measured it (no percentile; labelled «dato de API-Football»). */
export interface ProviderFigure {
  key: string;
  unit: "por_90" | "total" | "por_partido";
  better: Better;
  value: Maybe<number>;
  matches_with_data: number;
  /** Share of the competition season's appearances (team-matches) that report it; under 0.8 the value is «sin_cobertura». */
  coverage: number;
  origin: "api_football";
}

export interface TeamRecord {
  matches: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  points: number;
}

export interface MatchPoint {
  fixture_id: number;
  kickoff_at: string;
  opponent: Ref;
  home: boolean;
  goals_for: number;
  goals_against: number;
  xg_for: Maybe<number>;
  xg_against: Maybe<number>;
  xg_for_avg5: Maybe<number>;
  xg_against_avg5: Maybe<number>;
}

export interface HalfSplit {
  goals_for_1h: number;
  goals_against_1h: number;
  goals_for_2h: number;
  goals_against_2h: number;
  matches_with_data: number;
}

export interface GameStates {
  minutes_leading: number;
  minutes_level: number;
  minutes_trailing: number;
  matches_led: number;
  points_ceded: number;
  matches_trailed: number;
  points_rescued: number;
  matches_with_data: number;
}

export interface PulseBin {
  label: string;
  start: number;
  rate: number;
  league_rate: number;
  index: Maybe<number>;
  low: Maybe<number>;
  high: Maybe<number>;
}

export interface Pulse {
  subject: "goles_a_favor" | "goles_en_contra" | "tarjetas";
  sigma_minutes: number;
  bootstrap: number;
  matches: number;
  bins: PulseBin[];
}

export interface GoalRef {
  fixture_id: number;
  minute: number;
  extra_minute?: number | null;
}

export interface IntervalBin {
  label: string;
  goals_for: number;
  goals_against: number;
  league_for: number;
  league_against: number;
  goals_for_list: GoalRef[];
  goals_against_list: GoalRef[];
}

export interface GoalIntervals {
  matches: number;
  bins: IntervalBin[];
}

export interface SurvivalPoint {
  label: string;
  minute: number;
  survival: number;
}

export interface Survival {
  matches: number;
  points: SurvivalPoint[];
  median_first_goal: Maybe<string>;
  level_at_half: Maybe<number>;
  league_points: SurvivalPoint[];
}

export interface TrendRow {
  key: string;
  family: "resultado" | "goles" | "goles_1t" | "corners" | "tarjetas";
  rule_key: Maybe<string>;
  line: number | null;
  hits: number;
  n: number;
  pct: number;
  wilson_low: number;
  wilson_high: number;
  league_pct: Maybe<number>;
  deviation_pts: Maybe<number>;
  fixture_ids: number[];
}

export interface TrendColumn {
  context: TrendContext;
  matches: number;
  rows: TrendRow[];
}

export interface RadarAxis {
  key: RadarKey;
  percentile: Maybe<number>;
  value: Maybe<number>;
}

export interface TeamBody {
  team: Ref;
  record: TeamRecord;
  figures: StatFigure[];
  radar: RadarAxis[];
  series: MatchPoint[];
  halves: Maybe<HalfSplit>;
  states: Maybe<GameStates>;
  pulse_for: Maybe<Pulse>;
  pulse_against: Maybe<Pulse>;
  pulse_cards: Maybe<Pulse>;
  intervals: Maybe<GoalIntervals>;
  survival: Maybe<Survival>;
  trends: ItemList<TrendRow>;
  matrix: Maybe<TrendColumn[]>;
  /** 1.1.0 (always sent; optional so the documents built before it still type). */
  provider_extras?: ProviderFigure[];
}

export interface StripItem {
  fixture_id: number;
  kickoff_at: string;
  opponent: Ref;
  minutes: number;
  starter: boolean;
  values: { key: string; value: Maybe<number> }[];
}

export interface PlayerBody {
  player: Ref;
  team: Maybe<Ref>;
  position: Maybe<PositionGroup>;
  appearances: number;
  starts: number;
  minutes: number;
  nineties: number;
  min_nineties: number;
  figures: StatFigure[];
  last5: StripItem[];
  recent_minutes: { fixture_id: number; minutes: number; starter: boolean }[];
  /** 1.1.0 (always sent; optional so the documents built before it still type). */
  provider_extras?: ProviderFigure[];
}

export interface ScatterPoint {
  player_id: number;
  shots_per90: number;
  on_target_pct: number;
}

export interface StatsEntity {
  role: EntityRole;
  subject: "equipo" | "jugador";
  competition: CompetitionSeasonRef;
  scope: StatsScope;
  context: StatsContext;
  matches: number;
  calc_version: string;
  computed_at: string;
  available_scopes: StatsScope[];
  available_competitions: CompetitionSeasonRef[];
  team: Maybe<TeamBody>;
  player: Maybe<PlayerBody>;
  scatter: Maybe<ScatterPoint[]>;
}

export interface StatsProfile extends ContractHead {
  entities: StatsEntity[];
}

// ── C-14 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type ParlayReason =
  | "ok"
  | "interruptor_apagado"
  | "sin_regla"
  | "no_ofrecer"
  | "menos_de_3_casas"
  | "linea_de_cuarto"
  | "empezado"
  | "sin_cobertura";

export interface Implied {
  value: number;
  pct: number;
  books: number;
  as_of: string;
  method: "proporcional_media_casas";
}

export interface HistoryMark {
  hits: number;
  n: number;
  pct: number;
  wilson_low: number;
  wilson_high: number;
  window: "u10_contexto";
  rule_key: string;
}

export interface SelectionMarks {
  selection: string;
  line: number;
  best_odds: number;
  bookmaker: string;
  model: Maybe<Probability>;
  implied: Maybe<Implied>;
  history: Maybe<HistoryMark>;
  parlay: { allowed: boolean; reason: ParlayReason };
  /** Private projection only (the owner's evaluation, decision D-EA-2). */
  model_shadow?: Maybe<Probability>;
}

export interface MarketMarks {
  key: string;
  unit: string;
  category: string;
  kind: string;
  period: string;
  subject: string;
  state: MarketState;
  state_reason: string;
  rule_key: Maybe<string>;
  model_origin: Maybe<string>;
  distribution: Maybe<{ k: number; or_more: boolean; p: number }[]>;
  selections: SelectionMarks[];
}

export interface MarketProbs extends ContractHead {
  fixture_id: number;
  kickoff_at: string;
  home: Ref;
  away: Ref;
  catalog_version: string;
  markets: ItemList<MarketMarks>;
}
