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
  /** api-football, or football-data.co.uk when it is the only source. */
  source?: string | null;
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
  /** The provider's photo URL as stored; null: initials, never a guessed URL. */
  photo_url?: string | null;
}

export interface TeamLineup {
  side: Side;
  formation: string | null;
  coach: string | null;
  players: LineupPlayer[];
  coach_provider_id?: number | null;
  /** The coach's photo as /coachs stored it; null when none is stored (initials, never a guessed URL). */
  coach_photo_url?: string | null;
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
  photo_url?: string | null;
  /** The position he played in this match (G, D, M, F). */
  position_played?: string | null;
  offsides?: number | null;
  dribbled_past?: number | null;
  penalties_won?: number | null;
  penalties_committed?: number | null;
  penalties_saved?: number | null;
}

/** What the fixture's payloads say beyond the score: referee, winner flags, half starts. */
export interface MatchFacts {
  referee: string | null;
  referee_country: string | null;
  home_winner: boolean | null;
  away_winner: boolean | null;
  first_half_at: Iso | null;
  second_half_at: Iso | null;
  observed_at: Iso;
  payload_hash: string;
  normalizer_version: string;
}

export interface Absence {
  side: Side | null;
  player: string | null;
  player_id: number | null;
  type: string | null;
  reason: string | null;
  /** The player's photo, when the provider has one. */
  photo_url?: string | null;
  /** The player's position as the provider files it. */
  position?: string | null;
  /** When the provider reported this absence. */
  fetched_at?: Iso | null;
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
  /** The provider's zone ("Promotion - Champions League"), as it words it. */
  description?: string | null;
  /** When the provider was last asked for this table (an unchanged answer moves only this). */
  checked_at?: Iso | null;
  /** Whether the table reflects every match played before this one. */
  table_state?: "FRESH" | "STALE" | "UNKNOWN" | "UNAVAILABLE";
  table_reason?: string;
  /** The provider's label of the table the row comes from ("Clausura", "Apertura - Group A"). */
  table?: string | null;
  table_key?: string | null;
  table_kind?: TableKind | null;
  table_teams?: number | null;
  /** The stage the table ranks, and its phase (null for an aggregate). */
  stage?: string | null;
  phase?: string | null;
  /** This match's own stage, from its round label. */
  fixture_stage?: string | null;
  /** Why this table: the match's stage, its phase's league stage (knock-out), or the league stage before it. */
  selection?: TableSelection | null;
  team_logo?: string | null;
}

/** full: the stage's table; group: one of several (groups, conferences); ranking: across groups
 * (third-placed teams); aggregate: several stages (an annual table); other: not a stage (periods). */
export type TableKind = "full" | "group" | "ranking" | "aggregate" | "other";
export type TableSelection = "fixture_stage" | "phase_league_stage" | "previous_stage";

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
  /** The whole table(s) the two rows come from. */
  standings_tables?: StandingsTable[];
  form: Section<TeamForm[]>;
  h2h: Section<H2HMatch[]>;
  live_states: Section<LiveState[]>;
  live_odds: Section<LiveQuote[]>;
  live_movement: Section<LiveMove[]>;
  facts?: MatchFacts | null;
}

export interface LiveTeam {
  id: number;
  name: string;
  logo_url?: string | null;
}

/** How much of a live match can actually be shown (0-100), from what is stored. */
export interface LiveCompleteness {
  score: number;
  level: "rich" | "partial" | "basic";
  signals: Record<
    "score" | "minute" | "events" | "stats" | "lineups" | "players" | "live_odds" | "markets",
    boolean
  >;
}

export interface LiveMatch {
  fixture_id: number;
  kickoff_at: Iso;
  competition: string;
  country: string | null;
  competition_id?: number | null;
  competition_logo?: string | null;
  competition_flag?: string | null;
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
  has_lineups?: boolean;
  has_player_stats?: boolean;
  completeness?: LiveCompleteness | null;
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
  /** The provider's photo URL as stored (profiles); null: initials. */
  photo_url?: string | null;
  team_logo?: string | null;
  national_team_logo?: string | null;
  /** The player's CLUB now (newest squad, else last club appearance) - never a national side. */
  team_id: number | null;
  team: string | null;
  /** "squad" | "appearances" - where the club came from. */
  club_source?: string | null;
  national_team_id?: number | null;
  national_team?: string | null;
  /** Whoever he last played for (club or national side). */
  last_team_id?: number | null;
  last_team?: string | null;
  /** Matches PLAYED (minutes > 0); an unused substitute is not an appearance. */
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

/** Where reference rows come from: the provider endpoint, the payload and when PrediGol last asked. */
export interface Provenance {
  source: string;
  observed_at: Iso | null;
  payload_hash: string | null;
  normalizer_version: string | null;
  checked_at: Iso | null;
}

export interface PlayerTransfer {
  transfer_date: string | null;
  /** The provider's text: a fee, "Loan", "Free", "N/A". */
  type: string | null;
  team_in_id: number | null;
  team_in_provider_id: number | null;
  team_in: string | null;
  team_out_id: number | null;
  team_out_provider_id: number | null;
  team_out: string | null;
}

export interface PlayerSidelined {
  type: string | null;
  start: string | null;
  end: string | null;
}

export interface PlayerTrophy {
  league: string | null;
  country: string | null;
  season: string | null;
  place: string | null;
}

/** The PROVIDER's season aggregate for one team in one competition (/players?league&season), as sent; its
 * rating is the provider's own metric. PrediGol's aggregate from the per-match statistics is `PlayerSeason`. */
export interface PlayerProviderSeason {
  season: number;
  provider_league_id: number;
  competition_id: number | null;
  competition: string | null;
  provider_team_id: number;
  team_id: number | null;
  team: string | null;
  national: boolean | null;
  appearances: number | null;
  lineups: number | null;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  yellow_cards: number | null;
  red_cards: number | null;
  rating: Dec | null;
  observed_at: Iso;
}

/** One team of a player's career as /players/teams lists it, seasons newest first. */
export interface PlayerCareerTeam {
  provider_team_id: number | null;
  team_id: number | null;
  team: string | null;
  team_logo: string | null;
  national: boolean | null;
  seasons: number[];
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
  transfers?: Section<PlayerTransfer[]> | null;
  sidelined?: Section<PlayerSidelined[]> | null;
  trophies?: Section<PlayerTrophy[]> | null;
  provider_seasons?: Section<PlayerProviderSeason[]> | null;
  career?: Section<PlayerCareerTeam[]> | null;
  provenance?: Record<string, Provenance>;
}

export type LeaderListName = "topscorers" | "topassists" | "topyellowcards" | "topredcards";

export interface Leader {
  rank: number;
  provider_player_id: number;
  player_id: number | null;
  name: string | null;
  photo_url: string | null;
  team_id: number | null;
  provider_team_id: number | null;
  team: string | null;
  team_logo: string | null;
  appearances: number | null;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  penalties_scored: number | null;
  yellow_cards: number | null;
  yellowred_cards: number | null;
  red_cards: number | null;
  /** The provider's rating (its own metric), as sent; null for its 0 (not rated). */
  rating: Dec | null;
  /** Matches of this season the provider played him in but rated 0 (not rated): its season rating counts each as 0. */
  unrated_matches: number;
}

export interface LeaderList {
  kind: LeaderListName;
  rows: Leader[];
  provenance: Provenance;
}

export interface SeasonRound {
  ordinal: number;
  round: string;
  stage: string;
  phase: string;
  dates: string[];
  is_current: boolean;
}

export interface CompetitionReference {
  competition_id: number;
  season: number;
  leaders: Section<LeaderList[]>;
  rounds: Section<SeasonRound[]>;
  rounds_provenance: Provenance | null;
  current_rounds: string[];
}

export interface ProviderPrediction {
  observed_at: Iso;
  winner_team_id: number | null;
  winner_name: string | null;
  winner_comment: string | null;
  win_or_draw: boolean | null;
  under_over: string | null;
  goals_home: string | null;
  goals_away: string | null;
  advice: string | null;
  percent_home: Dec | null;
  percent_draw: Dec | null;
  percent_away: Dec | null;
  comparison: Record<string, { home?: string; away?: string }> | null;
  payload_hash: string;
  normalizer_version: string;
}

/** Admin only: the provider's own forecast - auxiliary, never PrediGol's model, never a pick. */
export interface ProviderPredictionView {
  fixture_id: number;
  label: string;
  history: ProviderPrediction[];
  checks: number;
}

export interface AdminCount {
  label: string;
  value: number | null;
  at: Iso | null;
  note: string | null;
  /** Stable machine name; the label is English text, the UI translates by this. */
  key?: string | null;
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

/** A row's home or away games; the provider gives no points for them (3 a win, 1 a draw). */
export interface TableSplit {
  played: number | null;
  wins: number | null;
  draws: number | null;
  losses: number | null;
  goals_for: number | null;
  goals_against: number | null;
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
  team_logo?: string | null;
  goals_diff?: number | null;
  /** The provider's zone ("Promotion - Libertadores"). */
  description?: string | null;
  zone_status?: string | null;
  home?: TableSplit | null;
  away?: TableSplit | null;
}

/** One stage of the season, from the fixtures' round labels ("Clausura - 12" -> Clausura). */
export interface SeasonStage {
  name: string;
  phase: string;
  kind: "league" | "knockout" | "qualifying" | "friendly";
  first_kickoff: Iso | null;
  last_kickoff: Iso | null;
  fixtures: number;
  finished: number;
  /** Kick-off of its last finished match. */
  last_finished?: Iso | null;
  tables: number;
  is_current: boolean;
}

/** One table of the provider's answer, kept apart from the season's other tables. */
export interface StandingsTable {
  key: string;
  label: string;
  stage: string | null;
  stages: string[];
  phase: string | null;
  kind: TableKind;
  method: "label" | "games" | "single" | "unmapped";
  agreement: string;
  note: string;
  is_current: boolean;
  rows: TableRow[];
}

export interface CompetitionTable {
  competition_id: number;
  season: number;
  snapshot_at: Iso;
  seasons?: number[];
  stages?: SeasonStage[];
  /** Each table apart, in stage order (Apertura, Clausura, groups, a ranking, an aggregate). */
  tables?: StandingsTable[];
  mapping_version?: string;
  /** Deprecated: every table's rows flattened. */
  rows: TableRow[];
}
