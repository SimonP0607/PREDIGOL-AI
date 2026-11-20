/**
 * C-16 «Disponibilidad» (plan PM, PM-02-05; backend `fbi.api.contracts.intelligence.availability`): what PrediGol has per
 * competition, season, datum and market (levels `coverage-levels-v1`), and the seven states of every block and market of a match.
 * Every route answers 404 while `FBI_AVAILABILITY` is off; nothing reads these types yet (the modules adopt them in PM-14-04).
 * 1.1.0 (PM-02-07): a cup season's phases (`phases`) and the phase that graded a match's blocks (`phase`), filled only while
 * `FBI_AVAILABILITY_PHASES` is on (`phases` empty and `phase` «todas» otherwise).
 */
import type { ContractHead, ItemList, Maybe, MarketState } from "./types_intelligence";

export type CoverageLevel = "A" | "B" | "C" | "D" | "MI";
export type CellReason =
  | "ninguno"
  | "heredado"
  | "muestra_insuficiente"
  | "menos_de_3_casas"
  | "menos_de_5_casas"
  | "no_entregado"
  | "sin_ventana"
  | "sin_medir";
export type MarketReason = Exclude<CellReason, "sin_medir"> | "sin_regla" | "sin_cobertura";
export type AvailabilityModule = "mi_parlay" | "picks" | "cuotas";
export type ModuleReason =
  | "ok"
  | "invalid_selection"
  | "quarter_line"
  | "started"
  | "market_not_priced"
  | "outlier_price"
  | "error_interno"
  | "MERCADO_NO_EVALUABLE"
  | "SIN_PROBABILIDAD"
  | "menos_de_3_casas"
  | "sin_precio";
export type AvailabilityScope = "directorio" | "competicion" | "partido" | "matriz" | "cambios";
export type CoverageFamily =
  "base" | "team_stats" | "xg" | "player_stats" | "referee" | "main_odds" | "stat_odds";
export type Declared = "si" | "no" | "sin_bandera";

export interface FamilyLevel {
  family: CoverageFamily;
  level: CoverageLevel;
}

export interface LevelCell {
  key: string;
  level: CoverageLevel;
  n: number;
  with_data: number;
  pct: Maybe<number>;
  provisional: boolean;
  reason: CellReason;
  measured_at: string;
}

export interface LevelCellPrivate extends LevelCell {
  measured_level: CoverageLevel;
  missed: boolean;
  pooled_seasons: number;
  declared: Declared;
}

export interface MarketCell extends LevelCell {
  median_books: Maybe<number>;
  settle_pct: Maybe<number>;
}

export interface MarketCellPrivate extends MarketCell {
  measured_level: CoverageLevel;
  missed: boolean;
  pooled_seasons: number;
  declared: Declared;
  catalogue_state: Maybe<MarketState>;
}

/** A cup's phases (PM-02-07). */
export type CupPhase = "previa" | "liga_o_grupos" | "eliminatoria";

/** The data cells of one phase of a cup season (the markets stay on «todas»). */
export interface PhaseAvailability<D extends LevelCell = LevelCell> {
  phase: CupPhase;
  data: D[];
}

export interface SeasonAvailability<
  D extends LevelCell = LevelCell,
  M extends MarketCell = MarketCell,
> {
  competition_season_id: number;
  season: number;
  phase: string;
  summary: CoverageLevel;
  summary_label: string;
  families: FamilyLevel[];
  data: D[];
  markets: M[];
  /** 1.1.0: empty for a league, a cup in one phase, or while `FBI_AVAILABILITY_PHASES` is off. */
  phases: PhaseAvailability<D>[];
}

export interface CompetitionAvailability<S extends SeasonAvailability = SeasonAvailability> {
  competition_id: number;
  name: string;
  country: Maybe<string>;
  tier: Maybe<number>;
  summary: CoverageLevel;
  summary_label: string;
  families: FamilyLevel[];
  /** Only on the competition's own route and the private matrix; empty in the directory. */
  seasons: S[];
}

export interface BlockAvailability {
  key: string;
  exists: boolean;
  level: Maybe<CoverageLevel>;
  n: number;
  provisional: boolean;
  reason: CellReason;
}

export interface ModuleVerdict {
  module: AvailabilityModule;
  ok: boolean;
  reason: ModuleReason;
}

export interface MarketAvailability {
  key: string;
  matrix_market: Maybe<string>;
  exists: boolean;
  coverage_ok: Maybe<boolean>;
  level: Maybe<CoverageLevel>;
  price_in_force: boolean;
  prob_computed: boolean;
  prob_authorised: boolean;
  settleable: boolean;
  reason: MarketReason;
  modules: ModuleVerdict[];
}

export interface SelectionVerdict {
  selection: string;
  line: number;
  books: number;
  mi_parlay: ModuleReason[];
}

export interface MarketAvailabilityPrivate extends MarketAvailability {
  catalogue_state: Maybe<MarketState>;
  selections: SelectionVerdict[];
}

export interface MatchAvailability<M extends MarketAvailability = MarketAvailability> {
  fixture_id: number;
  kickoff_at: string;
  competition_season_id: Maybe<number>;
  /** 1.1.0: the phase whose cells graded the blocks («todas» unless a cup match's phase was measured and the switch is on). */
  phase: "todas" | CupPhase;
  blocks: BlockAvailability[];
  markets: M[];
  notes: "muestra_insuficiente"[];
}

export interface LevelChange {
  competition_season_id: number;
  phase: string;
  kind: "datum" | "market";
  key: string;
  old_level: Maybe<CoverageLevel>;
  new_level: CoverageLevel;
  reason: "primera_medida" | "sube" | "baja" | "incumple_una_vez";
  n: Maybe<number>;
  changed_at: string;
}

export interface Discrepancy {
  day: string;
  fixture_id: number;
  module: string;
  key: string;
  shown: boolean;
  matrix: boolean;
  reason: string;
  observed_at: string;
}

/** C-16, public projection: `/availability/competitions`, `/availability/competitions/{id}`, `/matches/{id}/availability`. */
export interface Availability extends ContractHead {
  rules_version: string;
  scope: AvailabilityScope;
  competitions: CompetitionAvailability[];
  match: Maybe<MatchAvailability>;
}

/** C-16, private projection: `/admin/availability/matrix` and `/admin/availability/changes`. */
export interface AvailabilityPrivate extends ContractHead {
  rules_version: string;
  scope: AvailabilityScope;
  competitions: CompetitionAvailability<SeasonAvailability<LevelCellPrivate, MarketCellPrivate>>[];
  match: Maybe<MatchAvailability<MarketAvailabilityPrivate>>;
  changes: ItemList<LevelChange>;
  discrepancies: ItemList<Discrepancy>;
}
