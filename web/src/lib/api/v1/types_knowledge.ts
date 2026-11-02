/**
 * A finished match put together as one object, in layers (plan F7, Match Knowledge `mk-v1`), as the API returns it.
 * Mirrors fbi.api.contracts.knowledge.
 *
 * The layers are FACTS of a match that is over: the result, the statistics of the teams, the events, the players, the
 * tactics and the story of the score, and the market from its opening to its close. Each says how far it can be trusted
 * (`status`), how fresh it is (`known_at`) and what it could not say (`notes`, stable codes). No pick, no forecast and no
 * recommendation is in them. Only the Admin Console's preview also gets `stored`: the row as the database keeps it, with
 * the decision layer's picks and the post-mortems among its nine layers, and the chain of rebuilds.
 */
import type { Iso, Section } from "./types";

export type KnowledgeLayerStatus = "ok" | "partial" | "missing" | "off";
export type KnowledgeCompleteness = "complete" | "partial" | "minimal";
export type KnowledgeSide = "home" | "away";
/** `[home, away]`. */
export type KnowledgePair = [number, number];

export interface KnowledgeLayer<D> {
  status: KnowledgeLayerStatus;
  known_at: Iso | null;
  /** Stable codes of what the layer could not say. */
  notes: string[];
  /** Null when the layer is `missing` or `off`. */
  data: D | null;
}

// ── the result ──────────────────────────────────────────────────────────────

export interface KnowledgeTie {
  format: string;
  legs: number;
  leg: number | null;
  aggregate: KnowledgePair | null;
  winner: KnowledgeSide | null;
  decided_by: string | null;
  shootout: KnowledgePair | null;
  contradicted: boolean;
}

export interface KnowledgeResult {
  /** The provider's status of the match: FT, AET, PEN, AWD, WO. */
  match_status: string;
  kickoff: Iso | null;
  /** The score of the 90 minutes: the one the markets settle on. */
  reg: KnowledgePair;
  outcome: "Home" | "Draw" | "Away";
  total: number;
  btts: boolean;
  decided_by: "regulation" | "extra_time" | "penalties";
  ht: KnowledgePair | null;
  /** The score after extra time (a shoot-out is not in it). */
  final: KnowledgePair | null;
  pen: KnowledgePair | null;
  neutral: boolean;
  /** The provider changed this result after first giving it. */
  corrected: boolean;
  tie: KnowledgeTie | null;
}

// ── the statistics of the teams ─────────────────────────────────────────────

/** What the provider counted for one team. A figure it did not give is null, never zero. */
export interface KnowledgeTeamFigures {
  shots: number | null;
  on_target: number | null;
  off_target: number | null;
  blocked: number | null;
  in_box: number | null;
  out_box: number | null;
  corners: number | null;
  fouls: number | null;
  offsides: number | null;
  yellow: number | null;
  red: number | null;
  saves: number | null;
  /** Percent of the ball. */
  possession: number | null;
  passes: number | null;
  passes_ok: number | null;
  xg: number | null;
  prevented: number | null;
}

export interface KnowledgeTeamStats {
  home: KnowledgeTeamFigures | null;
  away: KnowledgeTeamFigures | null;
}

// ── the events ──────────────────────────────────────────────────────────────

export type KnowledgePeriod = "1H" | "2H" | "ET" | "PEN";

export interface KnowledgeEventLine {
  seq: number;
  kind: string;
  period: KnowledgePeriod;
  minute: number;
  /** Stoppage time: minute 90, extra 4 is 90+4. */
  extra: number | null;
  side: KnowledgeSide | null;
  player_side: KnowledgeSide | null;
  player: number | null;
  name: string | null;
  assist: number | null;
  assist_name: string | null;
  pair: number | null;
  flags: string[];
}

export interface KnowledgeEventChecks {
  reg: boolean | null;
  ht: boolean | null;
  et: boolean | null;
  pen: boolean | null;
  cards: boolean | null;
  listed: KnowledgePair | null;
}

export interface KnowledgeEvents {
  rules: string;
  n: number;
  counts: Record<string, number>;
  by_period: Partial<Record<KnowledgePeriod, KnowledgePair>>;
  check: KnowledgeEventChecks;
  goals: KnowledgeEventLine[];
  missed: KnowledgeEventLine[];
  shootout: KnowledgeEventLine[];
  cards: KnowledgeEventLine[];
  var: KnowledgeEventLine[];
}

// ── the players ─────────────────────────────────────────────────────────────

export interface KnowledgeTopPlayer {
  player_id: number;
  name: string | null;
  rating: number | null;
  minutes: number | null;
  goals: number;
  assists: number;
}

export interface KnowledgePlayersSide {
  listed: number;
  played: number;
  started: number;
  came_on: number;
  /** The best rated, at most three. */
  top: KnowledgeTopPlayer[];
  captain_id: number | null;
}

export interface KnowledgePlayers {
  home: KnowledgePlayersSide | null;
  away: KnowledgePlayersSide | null;
  goals_with_no_player: number;
}

// ── the tactics and the story of the score ──────────────────────────────────

export interface KnowledgeSubstitution {
  minute: number;
  /** The lead of the side that made it at that moment (negative: behind). Null when the events do not give the score. */
  lead: number | null;
}

export interface KnowledgeTacticsSide {
  formation: string | null;
  substitutions: KnowledgeSubstitution[];
}

export interface KnowledgeStory {
  /** Which sides were ahead at some moment. */
  ahead: { home: boolean; away: boolean };
  lead_changes: number;
  /** Minutes of the 90 in which each side led, or neither did. */
  minutes: { home_ahead: number; level: number; away_ahead: number };
  first_goal: { minute: number; side: KnowledgeSide } | null;
  last_goal_minute: number | null;
  /** The side that lost the man, and its lead at that moment. */
  first_dismissal: { minute: number; side: KnowledgeSide; lead: number } | null;
}

export interface KnowledgeTactics {
  home: KnowledgeTacticsSide | null;
  away: KnowledgeTacticsSide | null;
  story: KnowledgeStory | null;
}

// ── the market ──────────────────────────────────────────────────────────────

/**
 * The provider's last pre-match prices: the middle of the bookmakers' (not de-vigged), read after the match. A price, so the Admin
 * Console's preview alone: a user is told what the market believed (`probabilities`), never what a bet would have paid.
 */
export interface KnowledgeMarketFinal {
  odds: Record<string, number>;
  books: number;
  at: Iso;
  minutes_to_kickoff: number;
}

export interface KnowledgeMarketBlock {
  /** Per selection, the consensus probability without the bookmakers' margin: [opening, closing]. */
  probabilities: Record<string, [number | null, number]>;
  books: number | null;
  opened_at: Iso | null;
  closed_at: Iso | null;
  minutes_to_kickoff: number | null;
  /** Over/Under and handicap: the line the market is read at. */
  line: number | null;
  /** Only in the Admin Console's preview: always null for a user. */
  final: KnowledgeMarketFinal | null;
}

export interface KnowledgeMarket {
  /** 1X2, OU, BTTS and AH, the ones that were quoted, in the order of the board. */
  markets: Record<string, KnowledgeMarketBlock>;
}

// ── the answer ──────────────────────────────────────────────────────────────

export interface KnowledgeQuality {
  /** The list of events gives the score of the 90 minutes. */
  events_give_the_score: boolean | null;
  /** Stable codes of what could not be said, or may not be right. */
  doubts: string[];
}

export interface AfterMatch {
  /** The rules that put it together: mk-v1. */
  version: string;
  completeness: KnowledgeCompleteness;
  built_at: Iso;
  known_at: Iso;
  quality: KnowledgeQuality;
  result: KnowledgeLayer<KnowledgeResult>;
  team_stats: KnowledgeLayer<KnowledgeTeamStats>;
  events: KnowledgeLayer<KnowledgeEvents>;
  players: KnowledgeLayer<KnowledgePlayers>;
  tactics: KnowledgeLayer<KnowledgeTactics>;
  market: KnowledgeLayer<KnowledgeMarket>;
}

export interface KnowledgeBuildStub {
  id: number;
  supersedes: number | null;
  built_at: Iso;
  known_at: Iso;
  completeness: KnowledgeCompleteness;
  content_hash: string;
}

/** The newest row as stored, with the rows it replaced. Admin preview only. */
export interface KnowledgeStoredBuild {
  id: number;
  supersedes: number | null;
  inputs_hash: string;
  content_hash: string;
  /** The nine layers, c1_result to c9_postmortem, exactly as stored. */
  layers: Record<string, Record<string, unknown>>;
  quality: Record<string, unknown>;
  /** Every build of the match, oldest first: a rebuild is a new row. */
  chain: KnowledgeBuildStub[];
}

export interface MatchKnowledge {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  /** `not_available` with a code (not_finished, not_settled_yet, not_followed, no_build_yet) when there is none. */
  knowledge: Section<AfterMatch | null>;
  /** Null for a user. */
  stored?: KnowledgeStoredBuild | null;
}
