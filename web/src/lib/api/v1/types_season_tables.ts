/**
 * BE-082 «season-tables» 1.0.0 (plan PM, PM-09-04; backend `fbi.api.contracts.season_tables`): the tables of a competition season
 * the provider does not give - an accumulated table, an average over several seasons and the places they give - computed from the
 * results and the competition's rules file (BE-075). `GET /competitions/{id}/season-tables` answers 404 while
 * `FBI_COMPETITION_TABLES` is off, and `empty` for a competition without such tables (today all but the Primera A of Colombia).
 * Nothing in it is estimated: the calculator «¿Qué pasa si…?» (PM-09-03) adds a chosen result to these figures.
 */

export interface SeasonTeam {
  team_id: number | null;
  provider_team_id: number;
  name: string;
  logo_url: string | null;
}

export interface SeasonRecord {
  season: number;
  played: number;
  points: number;
}

export interface TieScope {
  points: number;
  goal_difference: number;
  goals_for: number;
  wins: number;
}

export interface SeasonTableRow {
  position: number;
  team: SeasonTeam;
  played: number;
  points: number;
  wins: number | null;
  draws: number | null;
  losses: number | null;
  goals_for: number | null;
  goals_against: number | null;
  goal_difference: number | null;
  /** An average only: the exact quotient, «points/played». */
  average: string | null;
  average_3: string | null;
  /** The average cut to three decimals, as the published tables show it. */
  average_3_cut: string | null;
  seasons: SeasonRecord[];
  window: number[];
  tie_scope: TieScope | null;
  shared_with: number[];
  decided_by: string | null;
  open_on: string | null;
}

export type ZoneState = "definitivo" | "provisional" | "condicional" | "empate_abierto";
export type PlaceState = "calculado" | "provisional" | "pendiente" | "no_calculado";

export interface SeasonZone {
  kind: string;
  target: string | null;
  positions: number[];
  /** Provider team ids. */
  teams: number[];
  state: ZoneState;
  note: string | null;
}

export interface SeasonPlace {
  competition: string;
  article: string | null;
  slot: string;
  source: "champion" | "cup_winner" | "table_rank";
  of: string | null;
  team: SeasonTeam | null;
  position: number | null;
  state: PlaceState;
  reason: string | null;
}

export interface SeasonTable {
  key: string;
  name: string;
  kind: "aggregate" | "average";
  complete: boolean;
  pending_matches: number;
  unverified_decisions: number;
  tiebreakers: string[];
  counts: string[];
  rows: SeasonTableRow[];
  zones: SeasonZone[];
  places: SeasonPlace[];
  rounding: Record<string, "igual" | "cambia_una_zona">;
  note: string | null;
}

export interface RemainingMatch {
  fixture_id: number | null;
  provider_fixture_id: number;
  round: string | null;
  kickoff_at: string | null;
  home: SeasonTeam;
  away: SeasonTeam;
  /** The keys of the tables this match counts in. */
  tables: string[];
}

export interface SeasonTables {
  contract: "season-tables";
  contract_version: "1.0.0";
  computed_by: string;
  competition_id: number;
  league_id: number;
  season: number;
  rules_version: number;
  rules_file: string;
  rules_sha256: string;
  points: { win: number; draw: number; loss: number };
  tables: SeasonTable[];
  champions: { tournament: string; team: SeasonTeam | null; state: "calculado" | "pendiente" }[];
  remaining: RemainingMatch[];
  unverified_decisions: number;
  computed_at: string;
}
