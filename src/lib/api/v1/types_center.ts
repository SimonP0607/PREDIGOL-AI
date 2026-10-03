/**
 * Match Center detail, Live board, Players and Admin - mirrored from
 * football-intelligence-v2 src/fbi/api/contracts/center.py.
 */
import type { ComponentHealth, Dec, Iso, Section } from "./types";

export type Side = "home" | "away";

export interface TeamStatLine {
  side: Side;
  shots: number | null;
  shots_on_target: number | null;
  shots_off_target: number | null;
  shots_blocked: number | null;
  shots_inside_box: number | null;
  shots_outside_box: number | null;
  corners: number | null;
  fouls: number | null;
  offsides: number | null;
  yellow_cards: number | null;
  red_cards: number | null;
  saves: number | null;
  possession_pct: Dec | null;
  passes: number | null;
  passes_accurate: number | null;
  expected_goals: Dec | null;
  fetched_at: Iso;
}

export interface MatchEvent {
  seq: number;
  minute: number;
  extra_minute: number | null;
  side: Side | null;
  player: string | null;
  player_id: number | null;
  assist: string | null;
  type: string;
  detail: string | null;
  comments: string | null;
}

export interface LineupPlayer {
  provider_player_id: number;
  player_id: number | null;
  name: string | null;
  number: number | null;
  position: string | null;
  grid: string | null;
  starter: boolean;
}

export interface TeamLineup {
  side: Side;
  formation: string | null;
  coach: string | null;
  players: LineupPlayer[];
}

export interface PlayerLine {
  provider_player_id: number;
  player_id: number | null;
  side: Side;
  name: string | null;
  minutes: number | null;
  rating: Dec | null;
  goals: number | null;
  assists: number | null;
  shots: number | null;
  shots_on: number | null;
  passes: number | null;
  key_passes: number | null;
  tackles: number | null;
  yellow_cards: number | null;
  red_cards: number | null;
  saves: number | null;
  substitute: boolean | null;
}

export interface Absence {
  side: Side | null;
  player: string | null;
  player_id: number | null;
  type: string | null;
  reason: string | null;
}

export interface StandingLine {
  side: Side;
  team: string;
  rank: number;
  points: number;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  form: string | null;
  group: string | null;
  snapshot_at: Iso;
  before_kickoff: boolean;
}

export interface FormMatch {
  fixture_id: number;
  kickoff_at: Iso;
  opponent: string;
  venue: "H" | "A";
  goals_for: number;
  goals_against: number;
  result: "W" | "D" | "L";
}

export interface TeamForm {
  side: Side;
  team: string;
  matches: FormMatch[];
}

export interface H2HMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: string;
  home: string;
  away: string;
  goals_home: number;
  goals_away: number;
}

export interface LiveState {
  observed_at: Iso;
  source: "fixture_feed" | "odds_feed";
  status: string;
  elapsed: number | null;
  extra: number | null;
  goals_home: number | null;
  goals_away: number | null;
}

export interface LiveQuote {
  market_key: string | null;
  provider_bet_id: number;
  selection: string;
  line: Dec;
  odds: Dec | null;
  suspended: boolean;
  main_line: boolean | null;
  captured_at: Iso;
  minute: number | null;
}

export interface LiveMove {
  market_key: string | null;
  selection: string;
  line: Dec;
  captured_at: Iso;
  minute: number | null;
  score: string | null;
  previous_odds: Dec | null;
  odds: Dec | null;
  delta: Dec | null;
  kind: "moved" | "withdrawn" | "offered" | "suspended" | "available" | "other";
}

export interface MatchCenter {
  fixture_id: number;
  status_group: string;
  statistics: Section<TeamStatLine[]>;
  events: Section<MatchEvent[]>;
  lineups: Section<TeamLineup[]>;
  players: Section<PlayerLine[]>;
  absences: Section<Absence[]>;
  standings: Section<StandingLine[]>;
  form: Section<TeamForm[]>;
  h2h: Section<H2HMatch[]>;
  live_states: Section<LiveState[]>;
  live_odds: Section<LiveQuote[]>;
  live_movement: Section<LiveMove[]>;
}

export interface LiveTeam {
  id: number;
  name: string;
}

export interface LiveMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: string;
  country: string | null;
  home: LiveTeam;
  away: LiveTeam;
  status: string;
  elapsed: number | null;
  extra: number | null;
  goals_home: number | null;
  goals_away: number | null;
  state_at: Iso;
  state_source: "fixture_feed" | "odds_feed";
  state_age_seconds: number;
  odds_feed_at: Iso | null;
  markets_offered: number | null;
  values_suspended: number | null;
  events: MatchEvent[];
  statistics: TeamStatLine[];
  main_odds: LiveQuote[];
  data_status: "ok" | "stale" | "no_odds";
}

export interface LiveBoard {
  matches: LiveMatch[];
  followed_by_fixture_feed: number;
  priced_by_odds_feed: number;
  last_fixture_feed_at: Iso | null;
  last_odds_feed_at: Iso | null;
}

export interface PlayerSummary {
  id: number;
  provider_player_id: number;
  name: string;
  nationality: string | null;
  position: string | null;
  birth_date: string | null;
  team_id: number | null;
  team: string | null;
  apps: number;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  avg_rating: Dec | null;
  last_played: Iso | null;
}

export interface PlayerSeason {
  competition: string;
  season: number;
  team: string | null;
  apps: number;
  starts: number;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  yellow_cards: number | null;
  red_cards: number | null;
  avg_rating: Dec | null;
}

export interface PlayerMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: string;
  team: string | null;
  opponent: string | null;
  minutes: number | null;
  rating: Dec | null;
  goals: number | null;
  assists: number | null;
  substitute: boolean | null;
}

export interface PlayerAbsence {
  fixture_id: number | null;
  kickoff_at: Iso | null;
  type: string | null;
  reason: string | null;
}

export interface PlayerDetail {
  player: PlayerSummary;
  firstname: string | null;
  lastname: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  seasons: Section<PlayerSeason[]>;
  matches: Section<PlayerMatch[]>;
  absences: Section<PlayerAbsence[]>;
}

export interface AdminCount {
  label: string;
  value: number | null;
  at: Iso | null;
  note: string | null;
}

export interface BackfillProgress {
  kind: string;
  total: number;
  done: number;
  pending: number;
  running: number;
  failed: number;
  other: number;
  last_completed_at: Iso | null;
}

export interface AdminError {
  run_id: number;
  job_type: string;
  status: string;
  started_at: Iso;
  error: string | null;
}

export interface BackupFile {
  name: string;
  location: string;
  bytes: number;
  modified_at: Iso;
}

export interface AdminQuota {
  date: string;
  spent: number;
  budget: number;
  remaining: number;
  plan_limit_per_day: number;
  ledger_api_calls: number;
  provider_status: ComponentHealth;
}

export interface AdminOverview {
  backend_version: string;
  code_version: string;
  schema_revision: string | null;
  database_bytes: number | null;
  worker: ComponentHealth;
  quota: AdminQuota;
  jobs_next: Record<string, string | null>;
  migration: Section<BackfillProgress[]>;
  captures: AdminCount[];
  errors: Section<AdminError[]>;
  quality: AdminCount[];
  backups: Section<BackupFile[]>;
}

export interface TableRow {
  rank: number;
  team_id: number;
  team: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  points: number;
  form: string | null;
  group: string | null;
}

export interface CompetitionTable {
  competition_id: number;
  season: number;
  snapshot_at: Iso;
  rows: TableRow[];
}
