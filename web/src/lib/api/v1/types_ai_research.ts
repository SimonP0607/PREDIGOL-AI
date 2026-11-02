/**
 * Research by entity and topic (plan IA, phase 2), as the Admin Console reads it. Mirrors fbi.api.contracts.ai_research.
 * Reading only: what research v2 kept in its cache - one answer per entity and topic -, the claims it wrote by class of source, type and status, what
 * each day of the cycle needed, paid, borrowed and reused, the week of comparison with v1 and the gate that decides whether v2 may replace it.
 * Nothing here searches, calls a model, writes a claim or changes a switch. Money and percentages travel as text (`Dec`), a moment as ISO text
 * (`Iso`), a day as `YYYY-MM-DD`.
 */
import type { Dec, Iso, Section } from "./types";

/** The owner's word for `FBI_AI_RESEARCH_V2`, and what the cycle does with it. */
export type ResearchWord = "off" | "shadow" | "on";

/** One row of `ai.feature_gates` for the gate `research_v2` (append-only: the newest decides). */
export interface ResearchGateRow {
  id: number;
  at: Iso;
  passed: boolean;
  decided_by: string;
  code_version: string | null;
  evidence_hash: string;
}

export interface ResearchSwitch {
  asked: ResearchWord;
  /** What the cycle does: `on` holds only while the newest row of the gate passed, otherwise it is `shadow`. */
  mode: ResearchWord;
  why: string;
  /** The typed claims are part of what the system reads and shows: only with `on` in force. */
  typed_visible: boolean;
  /** The newest row of the gate says it passed (false also when there is none). */
  gate_passed: boolean;
  /** When the newest row was written; null = the gate never ran. */
  gate_at: Iso | null;
  history: ResearchGateRow[];
}

/** One topic of the research and what the cache holds for it. */
export interface TopicRow {
  topic: string;
  /** What an answer is about: TEAM for the first two topics, MATCH for the preview. */
  entity: string;
  /** The levels of the tiered search that serve the topic. */
  levels: number[];
  /** The topic as the code names it for the owner (Spanish). */
  label: string;
  /** How long an answer is reused while the nearest kick-off of the entity is farther than the late window. */
  early_hours: number;
  late_hours: number;
  entries: number;
  fresh: number;
  expired: number;
  /** Times an answer was read instead of searched again. */
  reuses: number;
  newest_at: Iso | null;
  last_reuse_at: Iso | null;
}

export interface ResearchFreshness {
  late_window_hours: number;
  topics: TopicRow[];
  /** Rows of the entity scope whose key this code does not read: a count, never guessed at. */
  unreadable: number;
}

/** One answer kept for an entity on a topic, the newest first. */
export interface AnswerRow {
  kind: string;
  id: number;
  /** The team, or `home vs away` for a match; null for an entity the page cannot name. */
  name: string | null;
  kickoff_at: Iso | null;
  topic: string;
  level: number | null;
  results: number | null;
  standing: boolean | null;
  /** The results by the tier of their domain. */
  tiers: Record<string, number>;
  fetched_at: Iso;
  expires_at: Iso;
  fresh: boolean;
  reuses: number;
  last_reuse_at: Iso | null;
  /** Typed claims about the entity retrieved in the window (a team's include its players'). */
  claims: number;
  claims_fresh: number;
}

/** The typed claims of one class of source (or one type of claim) by status. */
export interface ClaimBreakdown {
  key: string;
  total: number;
  fresh: number;
  by_status: Record<string, number>;
}

export interface ResearchClaims {
  total: number;
  fresh: number;
  /** About a team or a player with no match: the next match of the team reads them too. */
  entity_scoped: number;
  match_scoped: number;
  /** Read from a page that sounded like an order to a model: they count as an unknown source. */
  flagged: number;
  by_status: Record<string, number>;
  by_class: ClaimBreakdown[];
  by_type: ClaimBreakdown[];
}

/** One Bogotá day of the cycle's passes. */
export interface ResearchDay {
  day: string;
  passes: number;
  /** Passes that ran research v2 (in shadow or in force). */
  passes_v2: number;
  passes_failed: number;
  passes_cut: number;
  searches: number;
  /** Searches research v2 needed: levels with an entity whose answer was not fresh. */
  demand: number;
  paid: number;
  shared: number;
  reused: number;
  pages: number;
  pages_known: number;
  claims: number;
  claims_new: number;
  exa_v1_usd: Dec;
  exa_v2_usd: Dec;
}

/** The pages research v2 remembers having read (scope `url`). */
export interface PageCache {
  remembered: number;
  fresh: number;
  reuses: number;
  read: number;
  known: number;
  unread: number;
  flagged: number;
}

/** The window of the page, v1 against research v2: the gate's arithmetic over days the gate may not accept - a reading, not evidence. */
export interface ResearchComparison {
  first: string;
  last: string;
  passes_in_shadow: number;
  passes_compared: number;
  passes_v2_failed: number;
  passes_v2_cut_short: number;
  searches_v1: number;
  searches_v2_alone: number;
  saved: number;
  saved_pct: Dec | null;
  reuse_pct: Dec | null;
  fixtures: number;
  facts_v1: number;
  facts_v2: number;
  found_by_v2: number;
  coverage_pct: Dec | null;
  coverage_players_pct: Dec | null;
  facts_per_match_v1: number | null;
  facts_per_match_v2: number | null;
  /** Facts of v1 that research v2 did not find: fixture, side, who, class. */
  missed_examples: unknown[][];
  exa_v1_searches: number;
  exa_v1_usd: Dec;
  exa_v2_searches: number;
  exa_v2_usd: Dec;
  extractor_calls: number;
  extractor_by_status: Record<string, number>;
  extractor_invalid_pct: Dec | null;
}

export interface GateWindow {
  first: string;
  last: string;
  days: number;
  anchor: string | null;
  anchored_by: string;
  stable_complete_days: number;
  eligible_on: string;
  complete: boolean;
}

export interface GateCheckRow {
  id: string;
  title: string;
  /** Null: it cannot be judged yet. */
  ok: boolean | null;
  mark: string;
  detail: Record<string, unknown>;
  revert: string | null;
}

/** The verdict of the gate, in the words of the gate itself. */
export type GateVerdict = "PASA" | "NO PASA" | "PENDIENTE POR TIEMPO REAL";

/** The gate of research v2 evaluated now. Evaluating writes nothing: only `python -m scripts.ia_research_gate evaluate --record` does. */
export interface ResearchGateView {
  verdict: GateVerdict | string;
  at: Iso;
  window: GateWindow;
  checks: GateCheckRow[];
  pending: string[];
  consequence: string | null;
  /** What the days gone show when the verdict is pending: not evidence of the gate. */
  preview: Record<string, unknown>;
}

export interface EntityResearchOverview {
  days: number;
  since: Iso;
  switch: ResearchSwitch;
  freshness: ResearchFreshness;
  answers: AnswerRow[];
  claims: ResearchClaims;
  per_day: ResearchDay[];
  pages: PageCache;
  comparison: Section<ResearchComparison | null>;
  gate: Section<ResearchGateView | null>;
}
